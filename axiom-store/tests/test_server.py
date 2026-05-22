"""
End-to-end tests for axiom_store.server — start a real TCP server on
an ephemeral port, send a real request over a real socket, assert the
real response.
"""

from pathlib import Path

import pytest

from axiom_store.protocol import Request
from axiom_store.test_utils import LocalServer, send_request


@pytest.fixture
def server(tmp_path: Path):
    s = LocalServer(tmp_path).start()
    yield s
    s.stop()


# ---------------------------------------------------------------------------
# End-to-end tests
# ---------------------------------------------------------------------------


def test_write_then_read_over_tcp(server: LocalServer):
    body = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nHello.\n"

    status, _ = send_request(
        server.host,
        server.port,
        Request(verb="WRITE", path="memory/facts/x.md", body=body),
    )
    assert status == "OK"

    status, response_body = send_request(
        server.host,
        server.port,
        Request(verb="READ", path="memory/facts/x.md", body=b""),
    )
    assert status == "OK"
    assert response_body == body


def test_read_not_found_over_tcp(server: LocalServer):
    status, _ = send_request(
        server.host,
        server.port,
        Request(verb="READ", path="memory/facts/nope.md", body=b""),
    )
    assert status == "NOT_FOUND"


def test_invalid_path_over_tcp(server: LocalServer):
    status, _ = send_request(
        server.host,
        server.port,
        Request(verb="READ", path="../escape.md", body=b""),
    )
    assert status == "BAD_REQUEST"


def test_schema_error_over_tcp(server: LocalServer):
    bad = b"---\ntype: fact\n---\n\nMissing created.\n"
    status, _ = send_request(
        server.host,
        server.port,
        Request(verb="WRITE", path="memory/facts/x.md", body=bad),
    )
    assert status == "SCHEMA_ERROR"


def test_list_over_tcp(server: LocalServer):
    body = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nHi.\n"
    for name in ("a.md", "b.md", "c.md"):
        send_request(
            server.host,
            server.port,
            Request(verb="WRITE", path=f"memory/facts/{name}", body=body),
        )
    status, response_body = send_request(
        server.host,
        server.port,
        Request(verb="LIST", path="memory/facts", body=b""),
    )
    assert status == "OK"
    assert response_body.decode("utf-8").split("\n") == ["a.md", "b.md", "c.md"]


def test_delete_over_tcp(server: LocalServer):
    body = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nHi.\n"
    send_request(
        server.host,
        server.port,
        Request(verb="WRITE", path="memory/facts/x.md", body=body),
    )
    status, _ = send_request(
        server.host,
        server.port,
        Request(verb="DELETE", path="memory/facts/x.md", body=b""),
    )
    assert status == "OK"
    status, _ = send_request(
        server.host,
        server.port,
        Request(verb="READ", path="memory/facts/x.md", body=b""),
    )
    assert status == "NOT_FOUND"


def test_many_sequential_requests(server: LocalServer):
    """One-shot connections must work back to back without state leakage."""
    body = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nHi.\n"
    for i in range(20):
        status, _ = send_request(
            server.host,
            server.port,
            Request(verb="WRITE", path=f"memory/facts/x{i}.md", body=body),
        )
        assert status == "OK"
    status, response_body = send_request(
        server.host,
        server.port,
        Request(verb="LIST", path="memory/facts", body=b""),
    )
    assert status == "OK"
    names = response_body.decode("utf-8").split("\n")
    assert len(names) == 20


def test_handles_coalesced_header_and_body(server: LocalServer):
    """
    Regression test: when TCP delivers the header block and the body in
    the same recv() (common on loopback), the server must correctly
    return the leftover body bytes from recv_until and stitch them onto
    recv_exact's read. This bug originally caused a BAD_REQUEST response
    instead of OK on every WRITE over loopback.
    """
    body = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nCoalesced body.\n"
    status, _ = send_request(
        server.host,
        server.port,
        Request(verb="WRITE", path="memory/facts/coalesced.md", body=body),
    )
    assert status == "OK"

    status, response_body = send_request(
        server.host,
        server.port,
        Request(verb="READ", path="memory/facts/coalesced.md", body=b""),
    )
    assert status == "OK"
    assert response_body == body
