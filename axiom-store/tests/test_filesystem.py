"""Tests for axiom_store.filesystem."""

from pathlib import Path

import pytest

from axiom_store.filesystem import InvalidVaultPath, VaultFS


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_vaultfs_creates_with_nonexistent_root(tmp_path: Path):
    # Construction does not require the root to exist yet.
    root = tmp_path / "vault-does-not-exist"
    fs = VaultFS(root)
    assert fs.root == root.resolve()


def test_vaultfs_rejects_root_that_is_a_file(tmp_path: Path):
    root = tmp_path / "not-a-dir"
    root.write_text("oops")
    with pytest.raises(InvalidVaultPath):
        VaultFS(root)


# ---------------------------------------------------------------------------
# write + read round trip
# ---------------------------------------------------------------------------


def test_write_then_read(tmp_path: Path):
    fs = VaultFS(tmp_path)
    fs.write("memory/facts/x.md", b"hello")
    assert fs.read("memory/facts/x.md") == b"hello"


def test_write_creates_parent_directories(tmp_path: Path):
    fs = VaultFS(tmp_path)
    fs.write("a/b/c/d.md", b"deep")
    assert (tmp_path / "a" / "b" / "c" / "d.md").read_bytes() == b"deep"


def test_write_overwrites_existing(tmp_path: Path):
    fs = VaultFS(tmp_path)
    fs.write("x.md", b"first")
    fs.write("x.md", b"second")
    assert fs.read("x.md") == b"second"


def test_write_preserves_unicode_bytes(tmp_path: Path):
    fs = VaultFS(tmp_path)
    payload = "café 🚀 中文\n".encode("utf-8")
    fs.write("unicode.md", payload)
    assert fs.read("unicode.md") == payload


def test_write_rejects_non_bytes(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(TypeError):
        fs.write("x.md", "not bytes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# read errors
# ---------------------------------------------------------------------------


def test_read_missing_raises_file_not_found(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.read("nope.md")


def test_read_directory_raises_is_a_directory(tmp_path: Path):
    fs = VaultFS(tmp_path)
    (tmp_path / "subdir").mkdir()
    with pytest.raises(IsADirectoryError):
        fs.read("subdir")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_removes_file(tmp_path: Path):
    fs = VaultFS(tmp_path)
    fs.write("x.md", b"bye")
    fs.delete("x.md")
    with pytest.raises(FileNotFoundError):
        fs.read("x.md")


def test_delete_missing_raises_file_not_found(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.delete("nope.md")


def test_delete_directory_refuses(tmp_path: Path):
    fs = VaultFS(tmp_path)
    (tmp_path / "subdir").mkdir()
    with pytest.raises(IsADirectoryError):
        fs.delete("subdir")


# ---------------------------------------------------------------------------
# list_dir
# ---------------------------------------------------------------------------


def test_list_dir_returns_sorted_filenames(tmp_path: Path):
    fs = VaultFS(tmp_path)
    fs.write("memory/facts/b.md", b"b")
    fs.write("memory/facts/a.md", b"a")
    fs.write("memory/facts/c.md", b"c")
    assert fs.list_dir("memory/facts") == ["a.md", "b.md", "c.md"]


def test_list_dir_excludes_subdirectories(tmp_path: Path):
    fs = VaultFS(tmp_path)
    fs.write("memory/facts/a.md", b"a")
    (tmp_path / "memory" / "facts" / "subfolder").mkdir()
    assert fs.list_dir("memory/facts") == ["a.md"]


def test_list_dir_empty_returns_empty_list(tmp_path: Path):
    fs = VaultFS(tmp_path)
    (tmp_path / "memory" / "facts").mkdir(parents=True)
    assert fs.list_dir("memory/facts") == []


def test_list_dir_missing_raises_file_not_found(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.list_dir("memory/facts")


def test_list_dir_on_file_raises_not_a_directory(tmp_path: Path):
    fs = VaultFS(tmp_path)
    fs.write("x.md", b"x")
    with pytest.raises(NotADirectoryError):
        fs.list_dir("x.md")


def test_list_dir_root_via_empty_string(tmp_path: Path):
    fs = VaultFS(tmp_path)
    fs.write("a.md", b"a")
    fs.write("b.md", b"b")
    assert fs.list_dir("") == ["a.md", "b.md"]


def test_list_dir_root_via_dot(tmp_path: Path):
    fs = VaultFS(tmp_path)
    fs.write("a.md", b"a")
    assert fs.list_dir(".") == ["a.md"]


# ---------------------------------------------------------------------------
# Path discipline — the security boundary
# ---------------------------------------------------------------------------


def test_rejects_path_traversal(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(InvalidVaultPath):
        fs.read("../outside.md")


def test_rejects_deep_path_traversal(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(InvalidVaultPath):
        fs.read("memory/../../etc/passwd")


def test_rejects_absolute_path(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(InvalidVaultPath):
        fs.read("/etc/passwd")


def test_rejects_empty_path(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(InvalidVaultPath):
        fs.read("")


def test_rejects_null_byte(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(InvalidVaultPath):
        fs.read("hello\x00.md")


def test_rejects_backslash(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(InvalidVaultPath):
        fs.read("memory\\facts\\x.md")


def test_rejects_non_string_path(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(InvalidVaultPath):
        fs.read(42)  # type: ignore[arg-type]


def test_path_traversal_applies_to_write_too(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(InvalidVaultPath):
        fs.write("../escape.md", b"data")


def test_path_traversal_applies_to_delete_too(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(InvalidVaultPath):
        fs.delete("../escape.md")


def test_path_traversal_applies_to_list_too(tmp_path: Path):
    fs = VaultFS(tmp_path)
    with pytest.raises(InvalidVaultPath):
        fs.list_dir("../escape")
