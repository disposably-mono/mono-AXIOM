"""
Text chunker for axiom-fetch.

Slices long Markdown into overlapping chunks suitable for retrieval.
Pure function: text in, list[Chunk] out. No vault, no schema, no I/O.

Strategy: fixed-size character chunks with overlap and soft word
boundaries. Each chunk is up to `chunk_size` characters. Each chunk
(except the first) overlaps with its predecessor by approximately
`overlap` characters. When a chunk would end mid-word, the cut is moved
backwards to the nearest whitespace within a small lookback window.

Sizing is in characters, not tokens. Tokenization is provider-specific
(Claude vs GPT vs local), so character count is the only universal,
deterministic unit. Token-aware chunking can be added in Phase 4 if
retrieval quality demands it.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CHUNK_SIZE = 2000  # ~500 tokens of English prose
DEFAULT_OVERLAP = 200  # ~10% of chunk_size

# When the naive cut would land mid-word, scan back up to this many chars
# looking for a clean break. If we don't find one, we cut at the naive
# position rather than blow up — pathological input shouldn't crash.
SOFT_BOUNDARY_LOOKBACK = 50

# Characters that count as soft boundaries. Whitespace is the main signal;
# punctuation is a fallback for prose with long unbroken phrases.
_SOFT_BOUNDARIES = frozenset(" \n\t.,;:!?")


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """
    A single chunk produced by the chunker.

      text:          the chunk content
      index:         position in the sequence, 0-based
      char_count:    len(text), duplicated so callers don't recompute
      overlap_chars: number of leading chars shared with the previous
                     chunk's tail. 0 for the first chunk.

    `chunk_total` is intentionally not here — the chunker returns a list,
    so the total is len(result). The pipeline reads it off the list when
    writing FETCH_CHUNK frontmatter.
    """

    text: str
    index: int
    char_count: int
    overlap_chars: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """
    Slice `text` into overlapping chunks.

    Args:
        text: The input text. May be any length, including empty.
        chunk_size: Maximum chunk length in characters. Must be positive.
        overlap: Number of characters each chunk shares with its
            predecessor. Must be non-negative and strictly less than
            chunk_size.

    Returns:
        A list of Chunk objects. Empty list if `text` is empty or
        whitespace-only.

    Raises:
        ValueError: On invalid arguments — non-string text, non-positive
            chunk_size, negative overlap, overlap >= chunk_size.
    """
    # ---- Argument validation ----
    if not isinstance(text, str):
        raise ValueError(f"text must be a string, got {type(text).__name__}")
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    if overlap < 0:
        raise ValueError(f"overlap must be non-negative, got {overlap}")
    if overlap >= chunk_size:
        raise ValueError(
            f"overlap ({overlap}) must be less than chunk_size ({chunk_size}); "
            "otherwise chunks would never advance"
        )

    # ---- Trivial cases ----
    stripped = text.strip()
    if not stripped:
        return []

    if len(stripped) <= chunk_size:
        return [
            Chunk(
                text=stripped,
                index=0,
                char_count=len(stripped),
                overlap_chars=0,
            )
        ]

    # ---- Main loop ----
    chunks: list[Chunk] = []
    cursor = 0
    text_len = len(stripped)
    while cursor < text_len:
        end = min(cursor + chunk_size, text_len)

        # Move the cut backwards to the nearest soft boundary, unless we're
        # at the very end of the text or the chunk is the trivial case.
        if end < text_len:
            min_end = cursor + overlap + 1
            end = _back_up_to_soft_boundary(stripped, end, min_end)

        chunk_body = stripped[cursor:end]
        overlap_chars = overlap if chunks else 0
        chunks.append(
            Chunk(
                text=chunk_body,
                index=len(chunks),
                char_count=len(chunk_body),
                overlap_chars=overlap_chars,
            )
        )

        if end >= text_len:
            break

        cursor = end - overlap
        if cursor < 0:
            cursor = 0

    return chunks


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _back_up_to_soft_boundary(text: str, end: int, min_end: int) -> int:
    """
    Move `end` backwards to the position just after the nearest soft
    boundary character within SOFT_BOUNDARY_LOOKBACK chars. Will not
    return a value less than `min_end` — forward progress is mandatory.

    If no boundary is found within the lookback window above `min_end`,
    returns `end` unchanged (naive cut, but at least we advance).

    Returns a position suitable for slicing as text[cursor:end] — i.e.
    one past the boundary character so the boundary stays with the
    preceding chunk.
    """
    floor = max(min_end, end - SOFT_BOUNDARY_LOOKBACK)
    # Walk backwards from end - 1 down to floor inclusive.
    for i in range(end - 1, floor - 1, -1):
        if text[i] in _SOFT_BOUNDARIES:
            return i + 1
    return end
