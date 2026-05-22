"""
Tests for axiom_queue.watchdog.

Strategy mirrors test_worker:
  - Pure functions (seconds_since, is_stalled) tested with fixed timestamps.
  - Step-level functions (scan, reclaim, step_once) tested against a
    live StoreClient with pre-seeded vault state.
  - run_watchdog tested with a thread + stop_event.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from axiom_queue.ids import now_iso
from axiom_queue.jobs import (
    STATUS_DEAD,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    Job,
    create_pending_job,
    read_job,
    write_job,
)
from axiom_queue.watchdog import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    STALL_THRESHOLD_SECONDS,
    is_stalled,
    reclaim,
    run_watchdog,
    scan_for_stalled_jobs,
    seconds_since,
    step_once,
)
from axiom_store import StoreClient
from axiom_store.test_utils import LocalServer


# ======================================================================
# Fixtures
# ======================================================================
@pytest.fixture
def live_store(tmp_path: Path):
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    server = LocalServer(tmp_path).start()
    client = StoreClient(host=server.host, port=server.port)
    try:
        yield client
    finally:
        server.stop()


def _running_job(claimed_at: str, attempts: int = 1, worker_id: str = "worker-1") -> Job:
    """Build a Job in running state with a fixed claimed_at timestamp."""
    base = create_pending_job("echo", payload={"message": "hi"})
    return Job(
        **{
            **base.to_frontmatter(),
            "status": STATUS_RUNNING,
            "worker_id": worker_id,
            "claimed_at": claimed_at,
            "updated_at": claimed_at,
            "attempts": attempts,
        }
    )


# ======================================================================
# seconds_since — pure time math
# ======================================================================
class TestSecondsSince:
    def test_exact_seconds_delta(self):
        assert seconds_since("2026-05-22T10:00:00Z", now="2026-05-22T10:00:05Z") == 5.0

    def test_minutes_delta(self):
        assert seconds_since("2026-05-22T10:00:00Z", now="2026-05-22T10:05:00Z") == 300.0

    def test_future_timestamp_returns_negative(self):
        assert seconds_since("2026-05-22T10:00:05Z", now="2026-05-22T10:00:00Z") == -5.0

    def test_zero_delta(self):
        assert seconds_since("2026-05-22T10:00:00Z", now="2026-05-22T10:00:00Z") == 0.0

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            seconds_since("not a timestamp", now="2026-05-22T10:00:00Z")

    def test_non_z_suffix_rejected(self):
        # The strict parser rejects +00:00 style.
        with pytest.raises(ValueError):
            seconds_since("2026-05-22T10:00:00+00:00", now="2026-05-22T10:00:00Z")


# ======================================================================
# is_stalled — predicate logic
# ======================================================================
class TestIsStalled:
    def test_running_past_threshold_is_stalled(self):
        job = _running_job(claimed_at="2026-05-22T10:00:00Z")
        # 6 minutes later — past the 5-minute threshold.
        assert is_stalled(job, now="2026-05-22T10:06:00Z") is True

    def test_running_under_threshold_not_stalled(self):
        job = _running_job(claimed_at="2026-05-22T10:00:00Z")
        # 1 minute later — well under threshold.
        assert is_stalled(job, now="2026-05-22T10:01:00Z") is False

    def test_exactly_at_threshold_is_stalled(self):
        # >= threshold counts as stalled.
        job = _running_job(claimed_at="2026-05-22T10:00:00Z")
        assert is_stalled(job, now="2026-05-22T10:05:00Z") is True

    def test_pending_job_never_stalled(self):
        job = create_pending_job("echo")
        # Even with a long-ago created_at, a pending job is never stalled.
        assert is_stalled(job, now="2099-01-01T00:00:00Z") is False

    def test_succeeded_job_never_stalled(self):
        base = create_pending_job("echo")
        succeeded = Job(
            **{
                **base.to_frontmatter(),
                "status": STATUS_SUCCEEDED,
                "result": {"echoed": "hi"},
                "updated_at": "2020-01-01T00:00:00Z",
            }
        )
        assert is_stalled(succeeded, now="2099-01-01T00:00:00Z") is False

    def test_dead_job_never_stalled(self):
        base = create_pending_job("echo")
        dead = Job(
            **{
                **base.to_frontmatter(),
                "status": STATUS_DEAD,
                "error": "broken",
                "updated_at": "2020-01-01T00:00:00Z",
                "attempts": 3,
            }
        )
        assert is_stalled(dead, now="2099-01-01T00:00:00Z") is False

    def test_failed_job_never_stalled(self):
        # Failed jobs have next_attempt_at; the worker handles their
        # readiness. The watchdog never reclaims them.
        base = create_pending_job("echo")
        failed = Job(
            **{
                **base.to_frontmatter(),
                "status": STATUS_FAILED,
                "error": "transient",
                "next_attempt_at": "2099-01-01T00:00:00Z",
                "updated_at": "2026-05-22T10:00:00Z",
                "attempts": 1,
            }
        )
        assert is_stalled(failed, now="2099-01-01T00:00:00Z") is False

    def test_running_without_claimed_at_treated_as_stalled(self):
        # Anomalous state — running but no claimed_at. Treat as stalled
        # so the next reclaim attempt can normalize it.
        base = create_pending_job("echo")
        anomalous = Job(
            id=base.id,
            kind=base.kind,
            status=STATUS_RUNNING,
            created_at=base.created_at,
            updated_at=base.updated_at,
            attempts=1,
            max_attempts=base.max_attempts,
            payload=base.payload,
            worker_id="worker-1",
            # claimed_at intentionally omitted.
        )
        assert is_stalled(anomalous, now="2026-05-22T10:00:00Z") is True

    def test_future_claimed_at_not_stalled(self):
        # Clock skew safety: a job claimed "in the future" is not stalled.
        job = _running_job(claimed_at="2099-01-01T00:00:00Z")
        assert is_stalled(job, now="2026-05-22T10:00:00Z") is False

    def test_custom_threshold(self):
        job = _running_job(claimed_at="2026-05-22T10:00:00Z")
        # Tight 30-second threshold; 1 minute is plenty stalled.
        assert is_stalled(job, threshold_seconds=30.0, now="2026-05-22T10:01:00Z") is True

    def test_default_threshold_is_300s(self):
        assert STALL_THRESHOLD_SECONDS == 300.0


# ======================================================================
# scan_for_stalled_jobs
# ======================================================================
class TestScanForStalledJobs:
    def test_empty_vault(self, live_store: StoreClient):
        assert scan_for_stalled_jobs(live_store) == []

    def test_no_running_jobs(self, live_store: StoreClient):
        # Pending and succeeded jobs are never stalled.
        write_job(live_store, create_pending_job("echo"))
        result = scan_for_stalled_jobs(live_store)
        assert result == []

    def test_finds_stalled_running_job(self, live_store: StoreClient):
        # Job claimed long ago.
        old_claim = "2020-01-01T00:00:00Z"
        job = _running_job(claimed_at=old_claim)
        write_job(live_store, job)

        result = scan_for_stalled_jobs(live_store, now="2026-05-22T10:00:00Z")
        assert len(result) == 1
        assert result[0].id == job.id

    def test_ignores_fresh_running_job(self, live_store: StoreClient):
        fresh_claim = "2026-05-22T09:59:30Z"  # 30s ago
        job = _running_job(claimed_at=fresh_claim)
        write_job(live_store, job)

        result = scan_for_stalled_jobs(live_store, now="2026-05-22T10:00:00Z")
        assert result == []

    def test_finds_multiple_stalled(self, live_store: StoreClient):
        old = "2020-01-01T00:00:00Z"
        for _ in range(3):
            write_job(live_store, _running_job(claimed_at=old))
        result = scan_for_stalled_jobs(live_store, now="2026-05-22T10:00:00Z")
        assert len(result) == 3


# ======================================================================
# reclaim — running → pending state transition
# ======================================================================
class TestReclaim:
    def test_running_becomes_pending(self, live_store: StoreClient):
        old = "2020-01-01T00:00:00Z"
        job = _running_job(claimed_at=old, attempts=2)
        write_job(live_store, job)

        reclaimed = reclaim(live_store, job)
        assert reclaimed.status == STATUS_PENDING
        assert reclaimed.worker_id is None
        assert reclaimed.claimed_at is None
        assert reclaimed.error is None
        assert reclaimed.next_attempt_at is None

    def test_attempts_unchanged(self, live_store: StoreClient):
        # The original claim counted the attempt; reclaim does not
        # grant a free retry.
        old = "2020-01-01T00:00:00Z"
        job = _running_job(claimed_at=old, attempts=2)
        write_job(live_store, job)

        reclaimed = reclaim(live_store, job)
        assert reclaimed.attempts == 2

    def test_persists_to_vault(self, live_store: StoreClient):
        old = "2020-01-01T00:00:00Z"
        job = _running_job(claimed_at=old)
        write_job(live_store, job)

        reclaim(live_store, job)
        reread = read_job(live_store, job.id)
        assert reread.status == STATUS_PENDING
        assert reread.worker_id is None

    def test_appends_reclaim_note_to_body(self, live_store: StoreClient):
        old = "2020-01-01T00:00:00Z"
        job = _running_job(claimed_at=old, worker_id="worker-42")
        write_job(live_store, job)

        reclaim(live_store, job)

        # Read raw bytes to inspect the body.
        raw = live_store.read(f"jobs/{job.id}.md").decode("utf-8")
        assert "Reclaimed by watchdog" in raw
        assert "worker-42" in raw

    def test_preserves_existing_body_content(self, live_store: StoreClient):
        # Simulate a handler that wrote a custom body, then a stall, then
        # a reclaim. The custom body content must survive.
        from axiom_store import render_frontmatter

        old = "2020-01-01T00:00:00Z"
        job = _running_job(claimed_at=old)
        custom_body = "## Custom handler progress\n\nStage 1 complete.\n"
        text = render_frontmatter(job.to_frontmatter(), custom_body)
        live_store.write(f"jobs/{job.id}.md", text.encode("utf-8"))

        reclaim(live_store, job)
        raw = live_store.read(f"jobs/{job.id}.md").decode("utf-8")
        assert "Stage 1 complete" in raw  # custom content preserved
        assert "Reclaimed by watchdog" in raw  # note appended

    def test_updated_at_advances(self, live_store: StoreClient):
        old = "2020-01-01T00:00:00Z"
        job = _running_job(claimed_at=old)
        write_job(live_store, job)

        reclaimed = reclaim(live_store, job)
        assert reclaimed.updated_at > job.updated_at


# ======================================================================
# step_once — full scan + reclaim cycle
# ======================================================================
class TestStepOnce:
    def test_empty_vault(self, live_store: StoreClient):
        assert step_once(live_store) == []

    def test_reclaims_stalled_jobs(self, live_store: StoreClient):
        old = "2020-01-01T00:00:00Z"
        for _ in range(2):
            write_job(live_store, _running_job(claimed_at=old))

        # Use a low threshold so the time-since-claim definitely exceeds it.
        reclaimed = step_once(live_store, threshold_seconds=1.0)
        assert len(reclaimed) == 2
        for j in reclaimed:
            assert j.status == STATUS_PENDING

    def test_leaves_fresh_jobs_alone(self, live_store: StoreClient):
        # Fresh job claimed just now.
        fresh = now_iso()
        write_job(live_store, _running_job(claimed_at=fresh))

        reclaimed = step_once(live_store)
        assert reclaimed == []


# ======================================================================
# run_watchdog — the main loop with stop_event
# ======================================================================
class TestRunWatchdog:
    def test_stops_immediately_when_event_preset(self, live_store: StoreClient):
        stop = threading.Event()
        stop.set()
        run_watchdog(live_store, stop_event=stop, scan_interval=0.05)

    def test_reclaims_stalled_jobs_in_loop(self, live_store: StoreClient):
        # Seed a stalled job, run watchdog, watch it get reclaimed.
        old = "2020-01-01T00:00:00Z"
        job = _running_job(claimed_at=old)
        write_job(live_store, job)

        stop = threading.Event()
        thread = threading.Thread(
            target=run_watchdog,
            kwargs={
                "client": live_store,
                "stop_event": stop,
                "scan_interval": 0.05,
                "threshold_seconds": 1.0,
            },
            daemon=True,
        )
        thread.start()

        # Wait for the reclaim to happen.
        deadline = time.time() + 3.0
        while time.time() < deadline:
            try:
                if read_job(live_store, job.id).status == STATUS_PENDING:
                    break
            except Exception:
                pass
            time.sleep(0.05)

        stop.set()
        thread.join(timeout=2.0)

        assert read_job(live_store, job.id).status == STATUS_PENDING

    def test_default_scan_interval(self):
        # Pin the locked Phase 2 value.
        assert DEFAULT_SCAN_INTERVAL_SECONDS == 10.0
