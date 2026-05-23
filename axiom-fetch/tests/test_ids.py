"""Tests for axiom_fetch.ids."""

from __future__ import annotations

import re

import pytest
from axiom_fetch.ids import chunk_id_for, new_source_id, now_iso


class TestNewSourceId:
    def test_starts_with_src_prefix(self):
        sid = new_source_id()
        assert sid.startswith("src-")

    def test_has_twelve_hex_chars_after_prefix(self):
        sid = new_source_id()
        suffix = sid[len("src-") :]
        assert len(suffix) == 12
        assert re.fullmatch(r"[0-9a-f]{12}", suffix)

    def test_two_calls_produce_different_ids(self):
        # UUID4 collision probability is astronomical; this is a sanity check.
        ids = {new_source_id() for _ in range(1000)}
        assert len(ids) == 1000


class TestChunkIdFor:
    def test_combines_source_and_padded_index(self):
        assert chunk_id_for("src-abc123def456", 7) == "src-abc123def456-0007"

    def test_index_zero(self):
        assert chunk_id_for("src-abc123def456", 0) == "src-abc123def456-0000"

    def test_large_index(self):
        assert chunk_id_for("src-abc123def456", 9999) == "src-abc123def456-9999"

    def test_index_above_9999_still_works(self):
        # 4-digit padding is for sort order; numbers above that are still
        # valid (just no longer zero-padded to 4).
        assert chunk_id_for("src-abc123def456", 12345) == "src-abc123def456-12345"

    def test_empty_source_id_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            chunk_id_for("", 0)

    def test_non_string_source_id_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            chunk_id_for(None, 0)  # type: ignore[arg-type]

    def test_negative_index_raises(self):
        with pytest.raises(ValueError, match="non-negative int"):
            chunk_id_for("src-abc", -1)

    def test_non_int_index_raises(self):
        with pytest.raises(ValueError, match="non-negative int"):
            chunk_id_for("src-abc", "0")  # type: ignore[arg-type]


class TestNowIso:
    def test_format_is_z_suffix(self):
        ts = now_iso()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts)

    def test_lexicographically_sortable(self):
        # Two consecutive calls should be sortable as strings.
        ts1 = now_iso()
        ts2 = now_iso()
        assert ts1 <= ts2
