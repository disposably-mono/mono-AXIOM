"""Tests for axiom_store.client.StoreClient against a real local server."""

from pathlib import Path

import pytest

from axiom_store.client import StoreClient, StoreError
from axiom_store.filesystem import InvalidVaultPath
from axiom_store.schema import SchemaError
from tests.test_server import _LocalServer  # reuse the threaded test server


@pytest.fixture
def setup(tmp_path: Path):
    server = _LocalServer(tmp_path).start()
    client = StoreClient(host=server.host, port=server.port)
    yield client, tmp_path
    server.stop()


VALID_FACT = b"---\ntype: fact\ncreated: '2026-05-21'\n---\n\nHello over TCP.\n"


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_client_write_then_read(setup):
    client, _ = setup
    client.write("memory/facts/x.md", VALID_FACT)
    assert client.read("memory/facts/x.md") == VALID_FACT


def test_client_list(setup):
    client, _ = setup
    client.write("memory/facts/a.md", VALID_FACT)
    client.write("memory/facts/b.md", VALID_FACT)
    assert client.list_dir("memory/facts") == ["a.md", "b.md"]


def test_client_list_empty_returns_empty_list(setup):
    client, tmp_path = setup
    (tmp_path / "memory" / "facts").mkdir(parents=True)
    assert client.list_dir("memory/facts") == []


def test_client_delete(setup):
    client, _ = setup
    client.write("memory/facts/x.md", VALID_FACT)
    client.delete("memory/facts/x.md")
    with pytest.raises(FileNotFoundError):
        client.read("memory/facts/x.md")


# ---------------------------------------------------------------------------
# Error translation: server statuses become Python exceptions
# ---------------------------------------------------------------------------


def test_client_read_missing_raises_file_not_found(setup):
    client, _ = setup
    with pytest.raises(FileNotFoundError):
        client.read("memory/facts/nope.md")


def test_client_invalid_path_raises_invalid_vault_path(setup):
    client, _ = setup
    with pytest.raises(InvalidVaultPath):
        client.read("../escape.md")


def test_client_schema_violation_raises_schema_error(setup):
    client, _ = setup
    bad = b"---\ntype: fact\n---\n\nMissing 'created' key.\n"
    with pytest.raises(SchemaError):
        client.write("memory/facts/x.md", bad)


def test_client_delete_missing_raises_file_not_found(setup):
    client, _ = setup
    with pytest.raises(FileNotFoundError):
        client.delete("memory/facts/nope.md")


def test_client_list_missing_raises_file_not_found(setup):
    client, _ = setup
    with pytest.raises(FileNotFoundError):
        client.list_dir("memory/facts")


def test_client_write_rejects_non_bytes(setup):
    client, _ = setup
    with pytest.raises(TypeError):
        client.write("x.md", "not bytes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Substitutability: the client interface matches the in-process store
# ---------------------------------------------------------------------------


def test_client_interface_matches_cached_vault_store():
    """
    Pin the shape: anywhere CachedVaultStore.read/write/delete/list_dir is
    used, StoreClient.read/write/delete/list_dir must work as a drop-in.
    Phase 2 onward depends on this.
    """
    from axiom_store.cache import CachedVaultStore

    expected = {"read", "write", "delete", "list_dir"}
    assert expected.issubset(dir(CachedVaultStore))
    assert expected.issubset(dir(StoreClient))
