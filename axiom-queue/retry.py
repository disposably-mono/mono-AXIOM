"""
Retry policy for axiom-queue.

Pure math. No I/O, no clock reads (except a single helper that returns
the next-attempt timestamp — and even that delegates to ids.now_iso).
This module decides:

  - how long to wait before the next attempt
  - whether the job should retry, become dead, or has succeeded
  - what the next status + next_attempt_at fields should be

The worker calls into here after every handler invocation to figure out
what to write back to the vault.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from axiom_queue.ids import now_iso
from axiom_queue.jobs import (
    STATUS_DEAD,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SUCCEEDED,
)

# Backoff parameters. Both locked in the Phase 2 schema discussion.
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 300.0  # 5-minute cap
JITTER_FRACTION = 0.25  # ±25% when jitter is enabled


@dataclass(frozen=True)
class RetryDecision:
    """
    The next state for a job after a handler attempt.

    next_status:
        - "succeeded" — handler returned cleanly. Terminal.
        - "failed"    — handler raised, retry is available. Worker will
                        re-run the job after next_attempt_at passes.
        - "dead"      — handler raised, no retries left. Terminal.

    next_attempt_at:
        ISO 8601 string when the next attempt may begin. Only meaningful
        when next_status == "failed". None for terminal statuses.

    delay_seconds:
        The wait the backoff computed. Useful for logging and tests.
        0.0 for terminal statuses.
    """

    next_status: str
    next_attempt_at: str | None
    delay_seconds: float


def compute_backoff(
    attempts: int,
    base: float = BASE_DELAY_SECONDS,
    cap: float = MAX_DELAY_SECONDS,
    jitter: bool = False,
    rng: random.Random | None = None,
) -> float:
    """
    Exponential backoff with an upper cap and optional jitter.

    delay = min(base * 2 ** attempts, cap)

    With jitter=True, multiplies by a random factor in
    [1 - JITTER_FRACTION, 1 + JITTER_FRACTION]. Pass `rng` for a
    seeded random.Random in tests.

    Args:
        attempts: number of completed attempts. Must be >= 1 — calling
                  with 0 means the handler hasn't run yet, which is a
                  bug in the worker. We raise rather than silently
                  return base * 2^0 = base, because that would mask
                  the bug.
        base: the unit delay in seconds. Default 1.0.
        cap: maximum delay, regardless of attempts. Default 300.0.
        jitter: if True, apply ±25% randomization.
        rng: optional seeded random.Random for deterministic tests.

    Returns:
        Delay in seconds. Always >= 0.
    """
    if attempts < 1:
        raise ValueError(f"compute_backoff requires attempts >= 1, got {attempts}")

    # Raw exponential. Clamp BEFORE jitter so jitter applies to the
    # capped value — otherwise a huge raw delay + negative jitter could
    # still produce a delay close to the cap, which feels surprising.
    raw = base * (2**attempts)
    clamped = min(raw, cap)

    if not jitter:
        return clamped

    r = rng if rng is not None else random
    factor = 1.0 + r.uniform(-JITTER_FRACTION, JITTER_FRACTION)
    return clamped * factor


def _now_plus_seconds(seconds: float) -> str:
    """
    Compute an ISO 8601 timestamp `seconds` in the future of now.

    Lives here (rather than in ids.py) because it's tightly coupled to
    the backoff calculation. `now_iso` is the canonical clock; this
    just shifts it.
    """
    base = datetime.now(timezone.utc)
    target = base + timedelta(seconds=seconds)
    return target.strftime("%Y-%m-%dT%H:%M:%SZ")


def decide_after_success() -> RetryDecision:
    """The handler returned cleanly. Job is done."""
    return RetryDecision(
        next_status=STATUS_SUCCEEDED,
        next_attempt_at=None,
        delay_seconds=0.0,
    )


def decide_after_failure(
    attempts: int,
    max_attempts: int,
    jitter: bool = False,
    rng: random.Random | None = None,
) -> RetryDecision:
    """
    The handler raised. Decide whether to retry or kill the job.

    Args:
        attempts: number of completed attempts INCLUDING the one that
                  just failed. So after the first failure, attempts=1.
        max_attempts: the job's max_attempts cap.
        jitter: pass through to compute_backoff.
        rng: pass through to compute_backoff.

    Returns:
        A RetryDecision with next_status of "failed" (retry pending)
        or "dead" (no retries left).
    """
    if attempts >= max_attempts:
        return RetryDecision(
            next_status=STATUS_DEAD,
            next_attempt_at=None,
            delay_seconds=0.0,
        )

    delay = compute_backoff(attempts, jitter=jitter, rng=rng)
    return RetryDecision(
        next_status=STATUS_FAILED,
        next_attempt_at=_now_plus_seconds(delay),
        delay_seconds=delay,
    )


def is_ready_to_retry(next_attempt_at: str | None, now: str | None = None) -> bool:
    """
    Return True if a failed job's backoff has expired and it's safe to
    re-claim. A None next_attempt_at means no backoff was scheduled —
    treat as ready.

    Both timestamps are compared as strings. The vault format
    (YYYY-MM-DDTHH:MM:SSZ) sorts correctly lexicographically because
    every field is fixed-width and UTC.
    """
    if next_attempt_at is None:
        return True
    current = now if now is not None else now_iso()
    return current >= next_attempt_at
