"""
End-to-end tests for axiom_store.server — start a real TCP server on
an ephemeral port, send a real request over a real socket, assert the
real response.
"""

import socket
import threading
import time
from pathlib import Path

import pytest

from axiom_store.cache import CachedVaultStore
from axiom_store.filesystem import VaultFS
from axiom_store.protocol import (
    HEADER_END,
    Request,
    format_request,
    parse_response_headers,
)
from axiom_store.server import handle_connection


def _send_request(host: str, port: int, request: Request) -> tuple[str, bytes]:
    """Connect, send one request, read one response, return (status, body)."""
    with socket.create_connection((host, port), timeout=5.0) as sock:
        sock.sendall(format_request(request))
        # Read until \n\n
        buf = bytearray()
        while HEADER_END not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
        header_part, _, after = bytes(buf).partition(HEADER_END)
        stub = parse_response_headers(header_part)
        body = bytearray(after)
        while len(body) < stub.content_length:
            chunk = sock.recv(min(4096, stub.content_length - len(body)))
            if not chunk:
                break
            body.extend(chunk)
        return stub.status, bytes(body)


class _LocalServer:
    """A one-shot server running in a thread, bound to an ephemeral port."""

    def __init__(self, vault_root: Path) -> None:
        self.store = CachedVaultStore(VaultFS(vault_root))
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))  # ephemeral port
        self.host, self.port = self.listener.getsockname()
        self.listener.listen(8)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        # Use a short accept timeout so we can poll the stop flag.
        self.listener.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except TimeoutError:
                continue
            with conn:
                handle_connection(conn, self.store)
        self.listener.close()

    def start(self) -> "_LocalServer":
        self._thread.start()
        # Tiny delay to avoid races on the very first connection
        time.sleep(0.02)
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)


@pytest.fixture
def server(tmp_path: Path):
    s = _LocalServer(tmp_path).start()
    yield s
    s.stop()


# ---------------------------------------------------------------------------
# End-to-end tests
# ---------------------------------------------------------------------------


def test_write_then_read_over_tcp(server: _LocalServer):
    body = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nHello.\n"

    status, _ = _send_request(
        server.host,
        server.port,
        Request(verb="WRITE", path="memory/facts/x.md", body=body),
    )
    assert status == "OK"

    status, response_body = _send_request(
        server.host,
        server.port,
        Request(verb="READ", path="memory/facts/x.md", body=b""),
    )
    assert status == "OK"
    assert response_body == body


def test_read_not_found_over_tcp(server: _LocalServer):
    status, _ = _send_request(
        server.host,
        server.port,
        Request(verb="READ", path="memory/facts/nope.md", body=b""),
    )
    assert status == "NOT_FOUND"


def test_invalid_path_over_tcp(server: _LocalServer):
    status, _ = _send_request(
        server.host,
        server.port,
        Request(verb="READ", path="../escape.md", body=b""),
    )
    assert status == "BAD_REQUEST"


def test_schema_error_over_tcp(server: _LocalServer):
    bad = b"---\ntype: fact\n---\n\nMissing created.\n"
    status, _ = _send_request(
        server.host,
        server.port,
        Request(verb="WRITE", path="memory/facts/x.md", body=bad),
    )
    assert status == "SCHEMA_ERROR"


def test_list_over_tcp(server: _LocalServer):
    body = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nHi.\n"
    for name in ("a.md", "b.md", "c.md"):
        _send_request(
            server.host,
            server.port,
            Request(verb="WRITE", path=f"memory/facts/{name}", body=body),
        )
    status, response_body = _send_request(
        server.host,
        server.port,
        Request(verb="LIST", path="memory/facts", body=b""),
    )
    assert status == "OK"
    assert response_body.decode("utf-8").split("\n") == ["a.md", "b.md", "c.md"]


def test_delete_over_tcp(server: _LocalServer):
    body = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nHi.\n"
    _send_request(
        server.host,
        server.port,
        Request(verb="WRITE", path="memory/facts/x.md", body=body),
    )
    status, _ = _send_request(
        server.host,
        server.port,
        Request(verb="DELETE", path="memory/facts/x.md", body=b""),
    )
    assert status == "OK"
    status, _ = _send_request(
        server.host,
        server.port,
        Request(verb="READ", path="memory/facts/x.md", body=b""),
    )
    assert status == "NOT_FOUND"


def test_many_sequential_requests(server: _LocalServer):
    """One-shot connections must work back to back without state leakage."""
    body = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nHi.\n"
    for i in range(20):
        status, _ = _send_request(
            server.host,
            server.port,
            Request(verb="WRITE", path=f"memory/facts/x{i}.md", body=body),
        )
        assert status == "OK"
    status, response_body = _send_request(
        server.host,
        server.port,
        Request(verb="LIST", path="memory/facts", body=b""),
    )
    assert status == "OK"
    names = response_body.decode("utf-8").split("\n")
    assert len(names) == 20


def test_handles_coalesced_header_and_body(server: _LocalServer):
    """
    Regression test: when TCP delivers the header block and the body in
    the same recv() (common on loopback), the server must correctly
    return the leftover body bytes from recv_until and stitch them onto
    recv_exact's read. This bug originally caused a BAD_REQUEST response
    instead of OK on every WRITE over loopback.
    """
    body = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nCoalesced body.\n"
    status, _ = _send_request(
        server.host,
        server.port,
        Request(verb="WRITE", path="memory/facts/coalesced.md", body=body),
    )
    assert status == "OK"

    status, response_body = _send_request(
        server.host,
        server.port,
        Request(verb="READ", path="memory/facts/coalesced.md", body=b""),
    )
    assert status == "OK"
    assert response_body == body
