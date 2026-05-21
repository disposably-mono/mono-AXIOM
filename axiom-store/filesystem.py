"""
Filesystem layer for axiom-store.

Owns all disk I/O for the vault. Operates on vault-relative paths (e.g.,
"memory/facts/python-gil.md"), resolving them against a configured vault
root. Validates paths to prevent traversal outside the root.

This layer knows nothing about caching, frontmatter parsing, schemas, or
TCP. It's the lowest layer: bytes in, bytes out, files on disk.

Errors:
    InvalidVaultPath - path fails discipline checks (traversal, absolute,
        null bytes, backslashes, empty)
    FileNotFoundError - target file or directory does not exist (for read,
        delete, list)
    PermissionError / OSError - underlying filesystem errors, propagated
        as-is
"""

from __future__ import annotations

from pathlib import Path


class InvalidVaultPath(ValueError):
    """Raised when a vault-relative path fails discipline checks."""


class VaultFS:
    """
    Filesystem operations over a vault directory.

    Every operation takes a vault-relative path string. The path is
    validated and resolved against the vault root before any I/O.

    Not thread-safe (single-process, TCP-serialized writes is the design
    assumption — see Documentation.md for the rationale).
    """

    def __init__(self, root: Path | str) -> None:
        """
        Args:
            root: the vault root directory. Will be expanduser'd and
                resolved to an absolute canonical path. The directory does
                not need to exist yet; operations will create files inside
                it (and `mkdir -p` intermediate folders on write).

        Raises:
            InvalidVaultPath: if the root resolves to something that
                exists but isn't a directory.
        """
        resolved = Path(root).expanduser().resolve()
        if resolved.exists() and not resolved.is_dir():
            raise InvalidVaultPath(f"Vault root {resolved} exists but is not a directory")
        self.root: Path = resolved

    # -----------------------------------------------------------------
    # Path discipline
    # -----------------------------------------------------------------

    def _resolve(self, vault_path: str) -> Path:
        """
        Resolve a vault-relative path to an absolute path inside the root.

        Rejects:
            - empty string
            - paths containing null bytes
            - paths containing backslashes (POSIX-only by project decision)
            - absolute paths
            - paths that resolve outside the vault root (traversal)

        Returns:
            The absolute resolved Path. Does NOT check whether the path
            exists — that's the caller's job.
        """
        if not isinstance(vault_path, str):
            raise InvalidVaultPath(f"vault path must be a string, got {type(vault_path).__name__}")
        if vault_path == "":
            raise InvalidVaultPath("vault path is empty")
        if "\x00" in vault_path:
            raise InvalidVaultPath("vault path contains null byte")
        if "\\" in vault_path:
            raise InvalidVaultPath("vault path contains backslash (POSIX only)")
        if vault_path.startswith("/"):
            raise InvalidVaultPath(f"vault path must be relative, got absolute: {vault_path!r}")

        # Join and resolve. resolve() collapses '..' segments, so any
        # attempt to escape the root will produce a path outside it,
        # which the membership check catches.
        candidate = (self.root / vault_path).resolve()

        # is_relative_to is Python 3.9+; we're on 3.14, so fine.
        if not candidate.is_relative_to(self.root):
            raise InvalidVaultPath(f"vault path escapes vault root: {vault_path!r}")

        return candidate

    # -----------------------------------------------------------------
    # Operations
    # -----------------------------------------------------------------

    def read(self, vault_path: str) -> bytes:
        """
        Read a vault file's raw bytes.

        Raises:
            InvalidVaultPath: path fails discipline checks.
            FileNotFoundError: file does not exist.
            IsADirectoryError: path exists but is a directory.
        """
        target = self._resolve(vault_path)
        return target.read_bytes()

    def write(self, vault_path: str, body: bytes) -> None:
        """
        Write bytes to a vault file. Creates parent directories as needed.
        Overwrites existing files.

        NOTE: Phase 1 uses direct write_bytes(), not the atomic
        write-temp-then-rename pattern. The vault is single-writer in
        Phase 1, so torn writes on crash are not a concern. Upgrade
        path is documented in the cache-layer notes.

        Raises:
            InvalidVaultPath: path fails discipline checks.
            IsADirectoryError: path exists and is a directory.
        """
        if not isinstance(body, bytes):
            raise TypeError(f"body must be bytes, got {type(body).__name__}")
        target = self._resolve(vault_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    def delete(self, vault_path: str) -> None:
        """
        Delete a vault file.

        Raises:
            InvalidVaultPath: path fails discipline checks.
            FileNotFoundError: file does not exist.
            IsADirectoryError: path exists but is a directory.
        """
        target = self._resolve(vault_path)
        if target.is_dir():
            raise IsADirectoryError(f"refusing to delete directory: {vault_path!r}")
        target.unlink()  # raises FileNotFoundError if missing

    def list_dir(self, vault_path: str) -> list[str]:
        """
        List filenames in a vault directory, sorted alphabetically.

        Returns only regular files. Subdirectories are not included.
        An empty directory returns [].

        Pass "" or "." to list the vault root.

        Raises:
            InvalidVaultPath: path fails discipline checks.
            FileNotFoundError: directory does not exist.
            NotADirectoryError: path exists but is a file.
        """
        # Special case: empty string and "." both mean "the vault root".
        # _resolve rejects empty string by default, so we short-circuit.
        if vault_path in ("", "."):
            target = self.root
        else:
            target = self._resolve(vault_path)

        if not target.exists():
            raise FileNotFoundError(f"vault directory does not exist: {vault_path!r}")
        if not target.is_dir():
            raise NotADirectoryError(f"vault path is not a directory: {vault_path!r}")

        return sorted(entry.name for entry in target.iterdir() if entry.is_file())
