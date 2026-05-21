"""
TCP client for axiom-store.

Provides a StoreClient class mirroring CachedVaultStore's interface:
read, write, delete, list_dir. Each method opens a fresh TCP connection,
sends one request, reads one response, closes. Server statuses are
translated into Python exceptions matching what the in-process store
would raise:

    NOT_FOUND      -> FileNotFoundError
    BAD_REQUEST    -> InvalidVaultPath
    SCHEMA_ERROR   -> SchemaError
    SERVER_ERROR   -> RuntimeError (with the server's message)

Anywhere a CachedVaultStore is acceptable, a StoreClient is acceptable.
"""

from __future__ import annotations

import socket

from axiom_store.filesystem import InvalidVaultPath
from axiom_store.protocol import (
    HEADER_END,
    Request,
    Response,
    format_request,
    parse_response_headers,
)
from axiom_store.schema import SchemaError


class StoreError(RuntimeError):
    """Raised when the server returns an error status that doesn't map
    to a more specific Python exception."""


class StoreClient:
    """
    TCP client for an axiom-store server.

    Mirrors the CachedVaultStore interface. Each call is one round-trip
    over a freshly opened TCP connection.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7070,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    # -----------------------------------------------------------------
    # Public API — mirrors CachedVaultStore
    # -----------------------------------------------------------------

    def read(self, vault_path: str) -> bytes:
        response = self._round_trip(Request(verb="READ", path=vault_path, body=b""))
        self._raise_for_status(response, vault_path)
        return response.body

    def write(self, vault_path: str, body: bytes) -> None:
        if not isinstance(body, bytes):
            raise TypeError(f"body must be bytes, got {type(body).__name__}")
        response = self._round_trip(Request(verb="WRITE", path=vault_path, body=body))
        self._raise_for_status(response, vault_path)

    def delete(self, vault_path: str) -> None:
        response = self._round_trip(Request(verb="DELETE", path=vault_path, body=b""))
        self._raise_for_status(response, vault_path)

    def list_dir(self, vault_path: str) -> list[str]:
        response = self._round_trip(Request(verb="LIST", path=vault_path, body=b""))
        self._raise_for_status(response, vault_path)
        if not response.body:
            return []
        return response.body.decode("utf-8").split("\n")

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _round_trip(self, request: Request) -> Response:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.sendall(format_request(request))
            return self._read_response(sock)

    def _read_response(self, sock: socket.socket) -> Response:
        # Read header block until \n\n
        buf = bytearray()
        while HEADER_END not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise StoreError("server closed connection before sending complete headers")
            buf.extend(chunk)

        header_bytes, _, after = bytes(buf).partition(HEADER_END)
        stub = parse_response_headers(header_bytes)

        # Read remaining body bytes
        body = bytearray(after)
        while len(body) < stub.content_length:
            chunk = sock.recv(min(4096, stub.content_length - len(body)))
            if not chunk:
                raise StoreError(
                    f"server closed connection after {len(body)} of "
                    f"{stub.content_length} body bytes"
                )
            body.extend(chunk)

        return Response(status=stub.status, body=bytes(body))

    def _raise_for_status(self, response: Response, path: str) -> None:
        status = response.status
        if status == "OK":
            return

        message = response.body.decode("utf-8", errors="replace")
        if status == "NOT_FOUND":
            raise FileNotFoundError(message or path)
        if status == "BAD_REQUEST":
            raise InvalidVaultPath(message or path)
        if status == "SCHEMA_ERROR":
            raise SchemaError(message or path)
        if status == "SERVER_ERROR":
            raise StoreError(message)
        raise StoreError(f"unknown server status {status!r}: {message}")
