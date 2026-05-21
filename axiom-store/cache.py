"""
Write-through cache layer for axiom-store.

Wraps a VaultFS instance, adding an in-memory cache (dict[str, bytes])
keyed by vault-relative path. The cache holds a coherent subset of what
is on disk:

    INVARIANT: if path in cache, then cache[path] == disk_contents(path)

This is maintained by writing to disk before the cache on every write,
and evicting the cache entry before/after every delete. Reads check the
cache first; misses populate it.

What this layer adds:
    - Hot reads return without touching disk
    - All reads through the same path return the same bytes (within
      a session, and absent out-of-band filesystem changes)
    - Observable hit/miss counters for testing and future ops metrics

What this layer does NOT add:
    - Cache invalidation on out-of-band filesystem changes (e.g., the
      user editing a vault file in their text editor). Phase 1 mitigation
      is "restart axiom-store after manual edits."
    - Schema validation (a separate layer)
    - Locking (single-process, TCP-serialized writes obviate it)
    - Eviction (cache grows unbounded; vault size is small enough that
      this is not a concern in Phase 1)

The interface mirrors VaultFS exactly. Anywhere a VaultFS is expected,
a CachedVaultStore can be substituted.
"""

from __future__ import annotations

from axiom_store.filesystem import VaultFS


class CachedVaultStore:
    """
    Write-through cache over a VaultFS.

    Holds a dict[str, bytes] keyed by vault-relative path. Reads consult
    the cache first; on miss, read from disk and populate. Writes go to
    disk first, then update the cache. Deletes remove from disk first,
    then evict the cache entry.

    Stats: self.stats["hits"] and self.stats["misses"] count read
    outcomes. Useful for tests and future ops metrics.
    """

    def __init__(self, fs: VaultFS) -> None:
        self._fs: VaultFS = fs
        self._cache: dict[str, bytes] = {}
        self.stats: dict[str, int] = {"hits": 0, "misses": 0}

    # -----------------------------------------------------------------
    # Read path
    # -----------------------------------------------------------------

    def read(self, vault_path: str) -> bytes:
        """
        Read a vault file's bytes, consulting the cache first.

        On a cache hit, returns the cached bytes without touching disk.
        On a cache miss, reads from disk via the inner VaultFS, populates
        the cache with the result, and returns the bytes.

        Errors from the inner VaultFS (InvalidVaultPath, FileNotFoundError,
        IsADirectoryError, etc.) propagate unchanged. The cache is not
        modified when the inner read raises.
        """
        if vault_path in self._cache:
            self.stats["hits"] += 1
            return self._cache[vault_path]

        # Miss: delegate to disk. If the disk read raises, we do NOT
        # populate the cache (the path may not be a valid file, or may
        # have failed for transient reasons). Counter still ticks — the
        # call was a miss, regardless of whether it succeeded.
        self.stats["misses"] += 1
        body = self._fs.read(vault_path)
        self._cache[vault_path] = body
        return body

    # -----------------------------------------------------------------
    # Write path
    # -----------------------------------------------------------------

    def write(self, vault_path: str, body: bytes) -> None:
        """
        Write bytes to a vault file, then update the cache.

        Disk first: if VaultFS.write raises, the cache is not touched and
        the invariant holds. On success, the cache is updated so the next
        read returns the new bytes without re-reading from disk.
        """
        self._fs.write(vault_path, body)
        self._cache[vault_path] = body

    # -----------------------------------------------------------------
    # Delete path
    # -----------------------------------------------------------------

    def delete(self, vault_path: str) -> None:
        """
        Delete a vault file, then evict the cache entry.

        Disk first: if VaultFS.delete raises (e.g., FileNotFoundError),
        the cache is not touched. On success, the cache entry is evicted
        (if present) so subsequent reads miss and re-read from disk
        (which will then raise FileNotFoundError, correctly).
        """
        self._fs.delete(vault_path)
        # pop with default to handle the case where the cache didn't have
        # this path. That's normal — the path may never have been read
        # since this process started.
        self._cache.pop(vault_path, None)

    # -----------------------------------------------------------------
    # List path (not cached)
    # -----------------------------------------------------------------

    def list_dir(self, vault_path: str) -> list[str]:
        """
        List filenames in a vault directory.

        Not cached — directory listings cheap enough relative to file
        reads, and caching them adds invalidation surface for marginal
        gain. Delegated directly to VaultFS.
        """
        return self._fs.list_dir(vault_path)
