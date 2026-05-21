"""
TCP server for axiom-store.

Accepts one connection at a time, reads a single request, dispatches to
the cached vault store, sends a single response, closes the connection.

Wire protocol per axiom_store.protocol: hybrid framing — `\\n`-delimited
header lines, blank line, then exactly Content-Length body bytes.

Concurrency model: single-threaded, sequential, one-shot connections.
This is the load-bearing assumption that lets CachedVaultStore be
lock-free. Do not change without revisiting the cache layer's design.
"""

from __future__ import annotations

import logging
import socket
from contextlib import closing
from pathlib import Path

from axiom_store.cache import CachedVaultStore
from axiom_store.filesystem import InvalidVaultPath, VaultFS
from axiom_store.frontmatter import FrontmatterError, parse_frontmatter
from axiom_store.protocol import (
    HEADER_END,
    MAX_BODY_BYTES,
    MAX_HEADER_BYTES,
    ProtocolError,
    Request,
    Response,
    format_response,
    parse_request_headers,
)
from axiom_store.schema import SchemaError, schema_for, validate

log = logging.getLogger("axiom_store.server")


class ConnectionClosed(Exception):
    """Raised when the peer closes the connection mid-message."""


# ---------------------------------------------------------------------------
# Socket reading helpers
# ---------------------------------------------------------------------------


def recv_until(
    sock: socket.socket,
    terminator: bytes,
    max_bytes: int,
) -> tuple[bytes, bytes]:
    """
    Read bytes from sock until `terminator` is found.

    Returns:
        (before, after) where `before` is everything before the terminator
        and `after` is anything that arrived in the same recv() AFTER the
        terminator. `after` is part of the next message (the body, in our
        protocol) and must be prepended to subsequent reads.

    Raises:
        ConnectionClosed: if the peer closes before the terminator appears.
        ProtocolError: if max_bytes is exceeded before the terminator appears.
    """
    buf = bytearray()
    while True:
        idx = buf.find(terminator)
        if idx != -1:
            before = bytes(buf[:idx])
            after = bytes(buf[idx + len(terminator) :])
            return before, after

        if len(buf) >= max_bytes:
            raise ProtocolError(f"header block exceeds {max_bytes} bytes without terminator")

        chunk = sock.recv(min(4096, max_bytes - len(buf) + len(terminator)))
        if not chunk:
            raise ConnectionClosed("peer closed connection while reading headers")
        buf.extend(chunk)


def recv_exact(
    sock: socket.socket,
    n: int,
    initial: bytes = b"",
) -> bytes:
    """
    Read exactly `n` bytes, allowing for `initial` bytes already pulled
    off the socket by a previous read (e.g., bytes that arrived after
    the header terminator).

    Raises:
        ConnectionClosed: if the peer closes before n bytes arrive.
    """
    if n == 0:
        # initial may carry leftover bytes that don't belong to us. In
        # the one-shot protocol, this shouldn't happen — content-length
        # is zero means no body. If `initial` is non-empty here, something
        # upstream is broken; better to fail loudly than swallow it.
        if initial:
            raise ProtocolError(
                f"got {len(initial)} extra bytes after headers but content-length is 0"
            )
        return b""

    if len(initial) >= n:
        # Already have enough (or too much). Same caveat: surplus bytes
        # mean a framing mismatch.
        if len(initial) > n:
            raise ProtocolError(f"got {len(initial)} bytes after headers but expected only {n}")
        return initial

    buf = bytearray(initial)
    while len(buf) < n:
        chunk = sock.recv(min(4096, n - len(buf)))
        if not chunk:
            raise ConnectionClosed(f"peer closed connection after {len(buf)} of {n} bytes")
        buf.extend(chunk)
    return bytes(buf)


# ---------------------------------------------------------------------------
# Dispatch — pure function, no sockets, fully testable
# ---------------------------------------------------------------------------


def dispatch(store: CachedVaultStore, request: Request) -> Response:
    """
    Handle a parsed Request against a CachedVaultStore. Returns a Response.

    Translates exceptions from lower layers into protocol statuses:
        InvalidVaultPath -> BAD_REQUEST
        FileNotFoundError -> NOT_FOUND
        SchemaError -> SCHEMA_ERROR
        FrontmatterError -> SCHEMA_ERROR (it's a write-time validation failure)
        TypeError, ValueError -> BAD_REQUEST
        Anything else -> SERVER_ERROR (and logged)
    """
    try:
        if request.verb == "READ":
            body = store.read(request.path)
            return Response(status="OK", body=body)

        if request.verb == "WRITE":
            # Validate frontmatter against the schema for this path, if any.
            schema = schema_for(request.path)
            if schema is not None:
                # Decode body for frontmatter parsing. We allow UTF-8 only.
                try:
                    text = request.body.decode("utf-8")
                except UnicodeDecodeError as e:
                    return Response(
                        status="BAD_REQUEST",
                        body=f"body is not valid UTF-8: {e}".encode("utf-8"),
                    )
                metadata, _ = parse_frontmatter(text)  # may raise FrontmatterError
                validate(metadata, schema)  # may raise SchemaError
            store.write(request.path, request.body)
            return Response(status="OK", body=b"")

        if request.verb == "DELETE":
            store.delete(request.path)
            return Response(status="OK", body=b"")

        if request.verb == "LIST":
            names = store.list_dir(request.path)
            # Body is filenames joined by newlines, UTF-8. Empty dir -> empty body.
            return Response(status="OK", body="\n".join(names).encode("utf-8"))

        # parse_request_headers already rejects unknown verbs, but defense
        # in depth never hurts.
        return Response(
            status="BAD_REQUEST",
            body=f"unknown verb: {request.verb!r}".encode("utf-8"),
        )

    except InvalidVaultPath as e:
        return Response(status="BAD_REQUEST", body=str(e).encode("utf-8"))
    except FileNotFoundError as e:
        return Response(status="NOT_FOUND", body=str(e).encode("utf-8"))
    except (SchemaError, FrontmatterError) as e:
        return Response(status="SCHEMA_ERROR", body=str(e).encode("utf-8"))
    except (TypeError, ValueError) as e:
        return Response(status="BAD_REQUEST", body=str(e).encode("utf-8"))
    except Exception as e:  # noqa: BLE001 — intentional catch-all for SERVER_ERROR
        log.exception("unexpected error handling %s %s", request.verb, request.path)
        return Response(
            status="SERVER_ERROR",
            body=f"{type(e).__name__}: {e}".encode("utf-8"),
        )


# ---------------------------------------------------------------------------
# Per-connection handler
# ---------------------------------------------------------------------------


def handle_connection(conn: socket.socket, store: CachedVaultStore) -> None:
    """
    Handle a single one-shot connection: read one request, send one
    response, close. Exceptions are caught and translated into responses
    where possible; truly fatal connection errors are logged and the
    connection is dropped.
    """
    try:
        header_bytes, leftover = recv_until(conn, HEADER_END, MAX_HEADER_BYTES)
        stub = parse_request_headers(header_bytes)
        if stub.content_length > MAX_BODY_BYTES:
            response = Response(
                status="BAD_REQUEST",
                body=f"body too large: {stub.content_length}".encode("utf-8"),
            )
            conn.sendall(format_response(response))
            return

        body = recv_exact(conn, stub.content_length, initial=leftover)
        request = Request(verb=stub.verb, path=stub.path, body=body)
        response = dispatch(store, request)

    except ProtocolError as e:
        log.warning("protocol error: %s", e)
        response = Response(status="BAD_REQUEST", body=str(e).encode("utf-8"))
    except ConnectionClosed as e:
        log.warning("connection closed mid-request: %s", e)
        return
    except Exception as e:  # noqa: BLE001
        log.exception("unexpected error in connection handler")
        response = Response(
            status="SERVER_ERROR",
            body=f"{type(e).__name__}: {e}".encode("utf-8"),
        )

    try:
        conn.sendall(format_response(response))
    except OSError as e:
        log.warning("failed to send response: %s", e)


# ---------------------------------------------------------------------------
# The server itself
# ---------------------------------------------------------------------------


def serve_forever(
    vault_root: Path | str,
    host: str = "127.0.0.1",
    port: int = 7070,
    backlog: int = 16,
) -> None:
    """
    Run the axiom-store TCP server until killed.

    Args:
        vault_root: path to the vault directory.
        host: bind address. Default "127.0.0.1" — loopback only. Do NOT
            bind to "0.0.0.0" without thinking hard about it; the protocol
            has no authentication.
        port: bind port. Default 7070.
        backlog: kernel accept queue size. Default 16.
    """
    fs = VaultFS(vault_root)
    store = CachedVaultStore(fs)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(backlog)
    log.info("axiom-store listening on %s:%d (vault=%s)", host, port, fs.root)

    try:
        with closing(listener):
            while True:
                conn, addr = listener.accept()
                log.debug("accepted connection from %s", addr)
                with closing(conn):
                    handle_connection(conn, store)
    except KeyboardInterrupt:
        log.info("shutting down on KeyboardInterrupt")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="axiom-store TCP server")
    parser.add_argument(
        "--vault",
        default=os.environ.get("VAULT_PATH", "./mono-vault"),
        help="Path to the vault directory (default: $VAULT_PATH or ./mono-vault)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("STORE_PORT", "7070")),
        help="Bind port (default: $STORE_PORT or 7070)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    serve_forever(args.vault, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
