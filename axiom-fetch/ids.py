"""
ID and timestamp helpers for axiom-fetch.

Centralized so tests can monkeypatch a single source for deterministic
IDs and timestamps. The Z suffix on timestamps (rather than +00:00) is
the vault's canonical UTC marker — short, unambiguous, and
lexicographically sortable with other timestamps in the same format.

Per-layer duplication is deliberate (same pattern as axiom-queue/ids.py):
each layer owns its own ID primitives. The implementations are identical
in spirit but scoped to the layer's naming conventions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def new_source_id() -> str:
    """
    Return a new source ID of the form 'src-<12-hex-chars>'.

    Twelve hex chars = 48 bits of entropy = ~281 trillion possibilities.
    More than enough for a personal vault; short enough to be human-greppable.
    """
    return f"src-{uuid4().hex[:12]}"


def chunk_id_for(source_id: str, chunk_index: int) -> str:
    """
    Return the canonical chunk ID for a given source and index.

    Format: '<source_id>-<index:04d>', e.g. 'src-abc123def456-0007'.
    Derivable from source + index, so no second UUID needed. Sorts
    naturally by filename within the chunks directory.
    """
    if not isinstance(source_id, str) or not source_id:
        raise ValueError(f"source_id must be a non-empty string, got {source_id!r}")
    if not isinstance(chunk_index, int) or chunk_index < 0:
        raise ValueError(f"chunk_index must be a non-negative int, got {chunk_index!r}")
    return f"{source_id}-{chunk_index:04d}"


def now_iso() -> str:
    """Current UTC time as 'YYYY-MM-DDTHH:MM:SSZ'."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
