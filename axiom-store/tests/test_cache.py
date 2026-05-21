"""Tests for axiom_store.cache."""

from pathlib import Path

import pytest

from axiom_store.cache import CachedVaultStore
from axiom_store.filesystem import InvalidVaultPath, VaultFS


@pytest.fixture
def store(tmp_path: Path) -> CachedVaultStore:
    """A CachedVaultStore over a fresh temp vault."""
    return CachedVaultStore(VaultFS(tmp_path))


# ---------------------------------------------------------------------------
# Basic round trips (same shape as VaultFS tests; the cache must not break
# any of the existing semantics)
# ---------------------------------------------------------------------------


def test_write_then_read(store: CachedVaultStore):
    store.write("memory/facts/x.md", b"hello")
    assert store.read("memory/facts/x.md") == b"hello"


def test_write_overwrites_existing(store: CachedVaultStore):
    store.write("x.md", b"first")
    store.write("x.md", b"second")
    assert store.read("x.md") == b"second"


def test_delete_removes_file(store: CachedVaultStore):
    store.write("x.md", b"bye")
    store.delete("x.md")
    with pytest.raises(FileNotFoundError):
        store.read("x.md")


def test_list_dir_passthrough(store: CachedVaultStore, tmp_path: Path):
    store.write("memory/facts/a.md", b"a")
    store.write("memory/facts/b.md", b"b")
    assert store.list_dir("memory/facts") == ["a.md", "b.md"]


def test_list_dir_missing_raises(store: CachedVaultStore):
    with pytest.raises(FileNotFoundError):
        store.list_dir("memory/facts")


def test_invalid_path_propagates(store: CachedVaultStore):
    with pytest.raises(InvalidVaultPath):
        store.read("../escape.md")


# ---------------------------------------------------------------------------
# Cache hit/miss behavior — the actual point of the layer
# ---------------------------------------------------------------------------


def test_read_after_write_is_a_hit(store: CachedVaultStore):
    store.write("x.md", b"data")
    # Write populates the cache, so the read should be a hit.
    store.read("x.md")
    assert store.stats == {"hits": 1, "misses": 0}


def test_first_read_is_a_miss(store: CachedVaultStore, tmp_path: Path):
    # Bypass the store to put a file on disk that the cache doesn't know about.
    (tmp_path / "x.md").write_bytes(b"on disk only")
    assert store.read("x.md") == b"on disk only"
    assert store.stats == {"hits": 0, "misses": 1}


def test_second_read_is_a_hit(store: CachedVaultStore, tmp_path: Path):
    (tmp_path / "x.md").write_bytes(b"data")
    store.read("x.md")  # miss, populates cache
    store.read("x.md")  # hit
    store.read("x.md")  # hit
    assert store.stats == {"hits": 2, "misses": 1}


def test_failed_read_does_not_populate_cache(store: CachedVaultStore):
    with pytest.raises(FileNotFoundError):
        store.read("does-not-exist.md")
    # Counter incremented (it was a miss attempt), cache did not gain a key.
    assert store.stats == {"hits": 0, "misses": 1}
    # Verify by trying again; should still be a miss, not a hit returning stale.
    with pytest.raises(FileNotFoundError):
        store.read("does-not-exist.md")
    assert store.stats == {"hits": 0, "misses": 2}


# ---------------------------------------------------------------------------
# Cache coherence — the invariant
# ---------------------------------------------------------------------------


def test_write_updates_cache(store: CachedVaultStore):
    store.write("x.md", b"first")
    store.write("x.md", b"second")
    # The second read should be a hit returning the new value.
    assert store.read("x.md") == b"second"
    assert store.stats["hits"] == 1
    assert store.stats["misses"] == 0


def test_delete_evicts_cache(store: CachedVaultStore, tmp_path: Path):
    store.write("x.md", b"data")
    store.read("x.md")  # hit, value is in cache
    store.delete("x.md")
    # After delete, the cache entry must be gone. Next read should miss
    # AND raise (file is gone on disk too).
    with pytest.raises(FileNotFoundError):
        store.read("x.md")


def test_delete_missing_does_not_touch_cache(store: CachedVaultStore):
    # Pre-populate the cache with an unrelated key
    store.write("other.md", b"keep me")
    store.read("other.md")  # in cache now

    with pytest.raises(FileNotFoundError):
        store.delete("does-not-exist.md")

    # The unrelated cached entry must still be there.
    store.read("other.md")
    assert store.stats["hits"] >= 1


def test_failed_write_does_not_pollute_cache(store: CachedVaultStore):
    # When VaultFS.write raises AFTER _resolve passes (e.g., a non-bytes
    # body), the cache must not be updated. This pins the "disk first,
    # then cache" ordering — the cache-update line never runs when the
    # underlying write fails.
    with pytest.raises(TypeError):
        store.write("legit-path.md", "not bytes")  # type: ignore[arg-type]

    # The cache must not hold "legit-path.md" — that path doesn't exist
    # on disk either, so a read goes through to VaultFS and raises.
    with pytest.raises(FileNotFoundError):
        store.read("legit-path.md")

    # That read was a real miss attempt against the underlying VaultFS,
    # confirming the cache had no entry.
    assert store.stats == {"hits": 0, "misses": 1}


def test_stats_start_at_zero(store: CachedVaultStore):
    assert store.stats == {"hits": 0, "misses": 0}


# ---------------------------------------------------------------------------
# Known limitation: out-of-band changes are NOT detected
# ---------------------------------------------------------------------------


def test_known_limitation_out_of_band_edit_returns_stale(store: CachedVaultStore, tmp_path: Path):
    """
    Documents the known Phase 1 limitation: if a vault file is modified
    out-of-band (e.g., the user editing it in their text editor) after
    being cached, the cache continues to return the stale value.

    This test pins the current behavior. When we add mtime-check
    invalidation in a later phase, this test should be UPDATED to expect
    the new value, not deleted — it remains a useful regression marker.
    """
    store.write("x.md", b"original")
    store.read("x.md")  # populate cache

    # Bypass the store to modify the file directly on disk.
    (tmp_path / "x.md").write_bytes(b"changed externally")

    # Cache still returns the original. This is the known limitation.
    assert store.read("x.md") == b"original"
