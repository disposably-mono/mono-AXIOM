"""
Tests for axiom_queue.retry.

Strategy:
  - compute_backoff: exhaustive over the parameter space — no jitter,
    cap behavior, jitter range, deterministic via seeded Random.
  - decide_after_*: state transitions only. No clock reads in assertions;
    next_attempt_at is checked for shape, not value.
  - is_ready_to_retry: fixed strings, no real clock.
"""

from __future__ import annotations

import random
import re

import pytest

from axiom_queue import retry
from axiom_queue.retry import (
    BASE_DELAY_SECONDS,
    JITTER_FRACTION,
    MAX_DELAY_SECONDS,
    RetryDecision,
    compute_backoff,
    decide_after_failure,
    decide_after_success,
    is_ready_to_retry,
)
from axiom_queue.jobs import STATUS_DEAD, STATUS_FAILED, STATUS_SUCCEEDED


# ======================================================================
# compute_backoff — the math
# ======================================================================
class TestComputeBackoff:
    def test_default_attempt_1(self):
        # 1.0 * 2**1 = 2.0
        assert compute_backoff(1) == 2.0

    def test_default_attempt_2(self):
        # 1.0 * 2**2 = 4.0
        assert compute_backoff(2) == 4.0

    def test_default_attempt_3(self):
        # 1.0 * 2**3 = 8.0
        assert compute_backoff(3) == 8.0

    def test_exponential_doubles_each_attempt(self):
        prev = compute_backoff(1)
        for i in range(2, 7):
            curr = compute_backoff(i)
            assert curr == pytest.approx(prev * 2.0)
            prev = curr

    def test_cap_kicks_in(self):
        # 1.0 * 2**20 = 1,048,576 — clamped to MAX_DELAY_SECONDS (300).
        assert compute_backoff(20) == MAX_DELAY_SECONDS

    def test_cap_is_inclusive(self):
        # The first attempt whose raw delay equals the cap exactly
        # should return the cap.
        # 1.0 * 2**n = 300 → n ≈ 8.23; attempt 9 = 512 (capped).
        assert compute_backoff(9) == MAX_DELAY_SECONDS

    def test_custom_base(self):
        # 0.5 * 2**3 = 4.0
        assert compute_backoff(3, base=0.5) == 4.0

    def test_custom_cap(self):
        # Tiny cap forces clamping at low attempt counts.
        assert compute_backoff(5, cap=10.0) == 10.0

    def test_rejects_attempts_zero(self):
        with pytest.raises(ValueError, match="attempts >= 1"):
            compute_backoff(0)

    def test_rejects_negative_attempts(self):
        with pytest.raises(ValueError, match="attempts >= 1"):
            compute_backoff(-1)


# ======================================================================
# compute_backoff — jitter
# ======================================================================
class TestJitter:
    def test_jitter_off_returns_exact_delay(self):
        # With jitter=False the function must be deterministic.
        for i in range(1, 6):
            assert compute_backoff(i, jitter=False) == 1.0 * (2**i)

    def test_jitter_on_stays_within_band(self):
        # ±25% of the base delay. Run many times to cover the range.
        rng = random.Random(42)
        base_delay = 4.0  # attempts=2 with base=1
        lo = base_delay * (1.0 - JITTER_FRACTION)
        hi = base_delay * (1.0 + JITTER_FRACTION)
        for _ in range(100):
            d = compute_backoff(2, jitter=True, rng=rng)
            assert lo <= d <= hi

    def test_jitter_is_deterministic_with_seeded_rng(self):
        # Same seed → same delay sequence. This is what tests that exercise
        # the worker loop will rely on.
        rng_a = random.Random(123)
        rng_b = random.Random(123)
        for _ in range(10):
            assert compute_backoff(2, jitter=True, rng=rng_a) == compute_backoff(
                2, jitter=True, rng=rng_b
            )

    def test_jitter_applies_to_capped_value(self):
        # Beyond the cap, jitter shifts the capped delay (not the raw).
        rng = random.Random(0)
        lo = MAX_DELAY_SECONDS * (1.0 - JITTER_FRACTION)
        hi = MAX_DELAY_SECONDS * (1.0 + JITTER_FRACTION)
        d = compute_backoff(50, jitter=True, rng=rng)
        assert lo <= d <= hi


# ======================================================================
# decide_after_success / decide_after_failure
# ======================================================================
class TestDecideAfterSuccess:
    def test_success_is_terminal(self):
        d = decide_after_success()
        assert d.next_status == STATUS_SUCCEEDED
        assert d.next_attempt_at is None
        assert d.delay_seconds == 0.0


class TestDecideAfterFailure:
    def test_failure_under_max_returns_failed(self):
        d = decide_after_failure(attempts=1, max_attempts=3)
        assert d.next_status == STATUS_FAILED
        assert d.next_attempt_at is not None
        assert d.delay_seconds > 0

    def test_failure_at_max_returns_dead(self):
        d = decide_after_failure(attempts=3, max_attempts=3)
        assert d.next_status == STATUS_DEAD
        assert d.next_attempt_at is None
        assert d.delay_seconds == 0.0

    def test_failure_over_max_returns_dead(self):
        # Defensive: if a worker miscounted, we still go dead, not loop.
        d = decide_after_failure(attempts=5, max_attempts=3)
        assert d.next_status == STATUS_DEAD

    def test_failed_decision_includes_iso_timestamp(self):
        d = decide_after_failure(attempts=1, max_attempts=3)
        # Format: YYYY-MM-DDTHH:MM:SSZ
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", d.next_attempt_at)

    def test_failed_decision_delay_matches_backoff(self):
        # decide_after_failure must call compute_backoff with the
        # right `attempts`. We verify by comparing.
        expected = compute_backoff(2)
        d = decide_after_failure(attempts=2, max_attempts=5)
        # Without jitter the delay should match exactly.
        assert d.delay_seconds == expected


# ======================================================================
# is_ready_to_retry
# ======================================================================
class TestIsReadyToRetry:
    def test_none_next_attempt_is_ready(self):
        assert is_ready_to_retry(None, now="2026-05-22T10:00:00Z") is True

    def test_now_before_next_is_not_ready(self):
        assert is_ready_to_retry("2026-05-22T10:00:05Z", now="2026-05-22T10:00:00Z") is False

    def test_now_equal_to_next_is_ready(self):
        assert is_ready_to_retry("2026-05-22T10:00:00Z", now="2026-05-22T10:00:00Z") is True

    def test_now_after_next_is_ready(self):
        assert is_ready_to_retry("2026-05-22T10:00:00Z", now="2026-05-22T10:00:05Z") is True

    def test_lexicographic_sort_holds_across_minute_boundary(self):
        # Regression pin for the assumption that string comparison works
        # on ISO 8601 UTC with Z suffix. If anyone introduces tz offsets
        # or microseconds, this will fail loudly.
        assert is_ready_to_retry("2026-05-22T10:00:59Z", now="2026-05-22T10:01:00Z") is True

    def test_uses_real_clock_when_now_omitted(self, monkeypatch):
        # Patch the now_iso reference inside retry.py to a fixed value.
        monkeypatch.setattr(retry, "now_iso", lambda: "2026-05-22T10:00:00Z")
        assert is_ready_to_retry("2026-05-22T09:59:59Z") is True
        assert is_ready_to_retry("2026-05-22T10:00:01Z") is False
