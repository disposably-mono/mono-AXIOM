"""
Tests for axiom_fetch.chunker.

Pure-function tests. All inputs are inline strings.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from axiom_fetch.chunker import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    Chunk,
    chunk_text,
)

# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


class TestArgumentValidation:
    def test_non_string_text_raises(self):
        with pytest.raises(ValueError, match="text must be a string"):
            chunk_text(12345)  # type: ignore[arg-type]

    def test_zero_chunk_size_raises(self):
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            chunk_text("hello", chunk_size=0)

    def test_negative_chunk_size_raises(self):
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            chunk_text("hello", chunk_size=-100)

    def test_negative_overlap_raises(self):
        with pytest.raises(ValueError, match="overlap must be non-negative"):
            chunk_text("hello", overlap=-1)

    def test_overlap_equals_chunk_size_raises(self):
        with pytest.raises(ValueError, match="must be less than chunk_size"):
            chunk_text("hello", chunk_size=100, overlap=100)

    def test_overlap_greater_than_chunk_size_raises(self):
        with pytest.raises(ValueError, match="must be less than chunk_size"):
            chunk_text("hello", chunk_size=100, overlap=200)


# ---------------------------------------------------------------------------
# Trivial cases
# ---------------------------------------------------------------------------


class TestTrivialCases:
    def test_empty_text_returns_empty_list(self):
        assert chunk_text("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert chunk_text("   \n\t   ") == []

    def test_short_text_returns_single_chunk(self):
        result = chunk_text("hello world", chunk_size=2000)
        assert len(result) == 1
        assert result[0].text == "hello world"
        assert result[0].index == 0
        assert result[0].char_count == len("hello world")
        assert result[0].overlap_chars == 0

    def test_text_exactly_chunk_size_returns_single_chunk(self):
        text = "x" * 100
        result = chunk_text(text, chunk_size=100, overlap=10)
        assert len(result) == 1
        assert result[0].text == text

    def test_leading_trailing_whitespace_stripped(self):
        result = chunk_text("   hello   ", chunk_size=2000)
        assert len(result) == 1
        assert result[0].text == "hello"


# ---------------------------------------------------------------------------
# Multi-chunk behavior
# ---------------------------------------------------------------------------


class TestMultipleChunks:
    def test_text_longer_than_chunk_size_produces_multiple_chunks(self):
        text = "x" * 5000
        result = chunk_text(text, chunk_size=1000, overlap=100)
        assert len(result) > 1

    def test_chunks_are_indexed_sequentially(self):
        text = "x" * 5000
        result = chunk_text(text, chunk_size=1000, overlap=100)
        for i, chunk in enumerate(result):
            assert chunk.index == i

    def test_first_chunk_has_zero_overlap(self):
        text = "x" * 5000
        result = chunk_text(text, chunk_size=1000, overlap=100)
        assert result[0].overlap_chars == 0

    def test_subsequent_chunks_have_overlap_chars_set(self):
        text = "x" * 5000
        result = chunk_text(text, chunk_size=1000, overlap=100)
        for chunk in result[1:]:
            assert chunk.overlap_chars == 100

    def test_chunks_do_overlap_with_predecessors(self):
        # Use distinct-character text so we can see overlap.
        text = "abcdefghij" * 500  # 5000 chars
        result = chunk_text(text, chunk_size=1000, overlap=100)
        # With no soft boundaries to back up to, the first chunk ends at
        # char 1000 and the next begins at char 900. So chunk[1]'s first
        # 100 chars should equal chunk[0]'s last 100 chars.
        assert result[1].text[:100] == result[0].text[-100:]

    def test_chunks_cover_the_whole_text(self):
        # The concatenation of unique parts (stripping overlap) should
        # equal the original text.
        text = "abcdefghij" * 500
        result = chunk_text(text, chunk_size=1000, overlap=100)

        reconstructed = result[0].text
        for chunk in result[1:]:
            # Skip the leading `overlap_chars` chars (already in previous).
            reconstructed += chunk.text[chunk.overlap_chars :]

        assert reconstructed == text

    def test_char_count_matches_text_length(self):
        text = "x" * 5000
        result = chunk_text(text, chunk_size=1000, overlap=100)
        for chunk in result:
            assert chunk.char_count == len(chunk.text)

    def test_no_chunk_exceeds_chunk_size(self):
        text = "x" * 5000
        result = chunk_text(text, chunk_size=1000, overlap=100)
        for chunk in result:
            assert chunk.char_count <= 1000


# ---------------------------------------------------------------------------
# Soft boundaries
# ---------------------------------------------------------------------------


class TestSoftBoundaries:
    def test_chunk_does_not_split_mid_word_when_space_available(self):
        # Build a string where the naive cut would land mid-word but a
        # space is within the lookback window.
        # chunk_size=50, so naive cut at position 50 (mid-zzz).
        # Lookback should find the space at position 40 and cut at 41,
        # leaving "word" for the next chunk.
        text = "a" * 40 + " word" + "z" * 100
        result = chunk_text(text, chunk_size=50, overlap=5)

        first = result[0].text
        # The first chunk should not end mid-word. The boundary at the
        # space means the chunk ends with a space; "word" and "zzz..."
        # both live in subsequent chunks.
        assert not first.endswith("z")
        # The clean break (the space) should be the boundary char.
        assert first.endswith(" ")
        # "word" should appear somewhere in the chunked output — the
        # second chunk in this case.
        assert any("word" in c.text for c in result)

    def test_no_soft_boundary_within_lookback_cuts_at_naive_position(self):
        # All "x"s — no soft boundary anywhere. We should cut at exactly
        # chunk_size and not crash.
        text = "x" * 5000
        result = chunk_text(text, chunk_size=100, overlap=10)
        # First chunk length should be exactly 100 (no boundary to back up to).
        assert result[0].char_count == 100

    def test_newline_counts_as_soft_boundary(self):
        # Newline within lookback should be used as the boundary.
        text = "a" * 40 + "\n" + "b" * 100
        result = chunk_text(text, chunk_size=50, overlap=5)
        # The newline at position 40 should be picked as the boundary.
        first = result[0].text
        assert first.endswith("\n") or first.endswith("a")
        # First chunk should not contain any "b"s.
        assert "b" not in first

    def test_punctuation_counts_as_soft_boundary(self):
        # Period within lookback should work.
        text = "a" * 40 + "." + "b" * 100
        result = chunk_text(text, chunk_size=50, overlap=5)
        first = result[0].text
        # First chunk should end at or just after the period.
        assert "." in first
        assert "b" not in first


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_chunk_size_is_2000(self):
        assert DEFAULT_CHUNK_SIZE == 2000

    def test_default_overlap_is_200(self):
        assert DEFAULT_OVERLAP == 200

    def test_defaults_produce_sensible_chunks(self):
        # A 10000-char document with defaults: expect ~5-6 chunks.
        text = "word " * 2000  # 10000 chars
        result = chunk_text(text)
        # 10000 chars, step = 1800, so chunks at roughly:
        # [0:2000], [1800:3800], [3600:5600], [5400:7400], [7200:9200], [9000:10000]
        # That's 6 chunks give or take soft boundaries.
        assert 4 <= len(result) <= 8


# ---------------------------------------------------------------------------
# Returns the right dataclass
# ---------------------------------------------------------------------------


class TestReturnShape:
    def test_returns_chunk_dataclass_instances(self):
        text = "x" * 5000
        result = chunk_text(text, chunk_size=1000, overlap=100)
        for chunk in result:
            assert isinstance(chunk, Chunk)

    def test_chunk_is_frozen(self):
        result = chunk_text("hello", chunk_size=2000)
        with pytest.raises(FrozenInstanceError):
            result[0].text = "tampered"  # type: ignore[misc]
