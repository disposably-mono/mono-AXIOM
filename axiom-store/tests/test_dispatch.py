"""
Tests for axiom_store.server.dispatch — the pure-function part of the
server. No sockets here; sockets are tested separately in test_server.py.
"""

from pathlib import Path

import pytest

from axiom_store.cache import CachedVaultStore
from axiom_store.filesystem import VaultFS
from axiom_store.protocol import Request, Response
from axiom_store.server import dispatch


@pytest.fixture
def store(tmp_path: Path) -> CachedVaultStore:
    return CachedVaultStore(VaultFS(tmp_path))


def _fact_body(extra: str = "") -> bytes:
    return f"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nHello.{extra}\n".encode()


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------


def test_dispatch_read_ok(store: CachedVaultStore):
    store.write("memory/facts/x.md", _fact_body())
    response = dispatch(store, Request(verb="READ", path="memory/facts/x.md", body=b""))
    assert response.status == "OK"
    assert response.body == _fact_body()


def test_dispatch_read_not_found(store: CachedVaultStore):
    response = dispatch(store, Request(verb="READ", path="memory/facts/nope.md", body=b""))
    assert response.status == "NOT_FOUND"


def test_dispatch_read_invalid_path(store: CachedVaultStore):
    response = dispatch(store, Request(verb="READ", path="../escape.md", body=b""))
    assert response.status == "BAD_REQUEST"


# ---------------------------------------------------------------------------
# WRITE
# ---------------------------------------------------------------------------


def test_dispatch_write_ok_no_schema(store: CachedVaultStore):
    # Path with no schema: free-form write succeeds.
    response = dispatch(
        store,
        Request(verb="WRITE", path="exports/dump.md", body=b"freeform body"),
    )
    assert response.status == "OK"
    assert response.body == b""
    assert store.read("exports/dump.md") == b"freeform body"


def test_dispatch_write_ok_with_valid_schema(store: CachedVaultStore):
    response = dispatch(
        store,
        Request(verb="WRITE", path="memory/facts/x.md", body=_fact_body()),
    )
    assert response.status == "OK"
    assert store.read("memory/facts/x.md") == _fact_body()


def test_dispatch_write_schema_violation_missing_required(store: CachedVaultStore):
    bad = b"---\ntype: fact\n---\n\nMissing created.\n"
    response = dispatch(
        store,
        Request(verb="WRITE", path="memory/facts/x.md", body=bad),
    )
    assert response.status == "SCHEMA_ERROR"
    # And the file MUST NOT have been written.
    response2 = dispatch(store, Request(verb="READ", path="memory/facts/x.md", body=b""))
    assert response2.status == "NOT_FOUND"


def test_dispatch_write_malformed_frontmatter(store: CachedVaultStore):
    bad = b"---\ntype: fact\n\nUnclosed fence body\n"
    response = dispatch(
        store,
        Request(verb="WRITE", path="memory/facts/x.md", body=bad),
    )
    assert response.status == "SCHEMA_ERROR"


def test_dispatch_write_invalid_utf8_body(store: CachedVaultStore):
    response = dispatch(
        store,
        Request(verb="WRITE", path="memory/facts/x.md", body=b"\xff\xfe not utf8"),
    )
    assert response.status == "BAD_REQUEST"


def test_dispatch_write_invalid_path(store: CachedVaultStore):
    response = dispatch(
        store,
        Request(verb="WRITE", path="../escape.md", body=b"data"),
    )
    assert response.status == "BAD_REQUEST"


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


def test_dispatch_delete_ok(store: CachedVaultStore):
    store.write("memory/facts/x.md", _fact_body())
    response = dispatch(store, Request(verb="DELETE", path="memory/facts/x.md", body=b""))
    assert response.status == "OK"
    response2 = dispatch(store, Request(verb="READ", path="memory/facts/x.md", body=b""))
    assert response2.status == "NOT_FOUND"


def test_dispatch_delete_not_found(store: CachedVaultStore):
    response = dispatch(store, Request(verb="DELETE", path="nope.md", body=b""))
    assert response.status == "NOT_FOUND"


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------


def test_dispatch_list_ok(store: CachedVaultStore):
    store.write("memory/facts/a.md", _fact_body())
    store.write("memory/facts/b.md", _fact_body())
    response = dispatch(store, Request(verb="LIST", path="memory/facts", body=b""))
    assert response.status == "OK"
    assert response.body.decode("utf-8").split("\n") == ["a.md", "b.md"]


def test_dispatch_list_empty(store: CachedVaultStore, tmp_path: Path):
    (tmp_path / "memory" / "facts").mkdir(parents=True)
    response = dispatch(store, Request(verb="LIST", path="memory/facts", body=b""))
    assert response.status == "OK"
    assert response.body == b""


def test_dispatch_list_not_found(store: CachedVaultStore):
    response = dispatch(store, Request(verb="LIST", path="memory/facts", body=b""))
    assert response.status == "NOT_FOUND"
