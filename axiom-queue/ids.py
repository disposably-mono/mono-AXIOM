"""
ID and timestamp helpers for axiom-queue.

Centralizing UUID and timestamp generation gives us exactly one place
to monkeypatch in tests, eliminating flaky time-based assertions.

`now_iso()` returns UTC timestamps in ISO 8601 with the trailing 'Z'
suffix — the canonical form across the vault.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def new_job_id() -> str:
    """Return a new UUID4 string for use as a job ID."""
    return str(uuid4())


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string ending in 'Z'."""
    # datetime.now(timezone.utc) gives '+00:00'; we normalize to 'Z'
    # so vault timestamps look the same as the ones humans hand-write.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
