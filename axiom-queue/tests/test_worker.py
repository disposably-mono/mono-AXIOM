"""
Tests for axiom_queue.worker.

Strategy:
  - Pure functions (scan_for_claimable_jobs, claim, execute, resolve)
    tested individually against a live StoreClient and pre-seeded vault.
  - step_once tested as integration of the four steps.
  - run_worker tested against a stop_event, with bounded iterations.

execute is the only one that doesn't touch the vault — it's a thin
wrapper over handlers.dispatch. Tested with the snapshot/restore
registry fixture from test_handlers.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from axiom_queue import handlers
from axiom_queue.handlers import HANDLERS, register
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
from axiom_queue.worker import (
    ClaimResult,
    ExecutionOutcome,
    claim,
    execute,
    make_worker_id,
    resolve,
    run_worker,
    scan_for_claimable_jobs,
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


@pytest.fixture
def isolated_registry():
    snapshot = dict(HANDLERS)
    try:
        yield
    finally:
        HANDLERS.clear()
        HANDLERS.update(snapshot)


WORKER_ID = "worker-test-1"


# ======================================================================
# make_worker_id
# ======================================================================
class TestMakeWorkerId:
    def test_includes_pid(self):
        import os

        wid = make_worker_id()
        assert wid.startswith("worker-")
        assert str(os.getpid()) in wid


# ======================================================================
# scan_for_claimable_jobs
# ======================================================================
class TestScanForClaimableJobs:
    def test_empty_vault(self, live_store: StoreClient):
        assert scan_for_claimable_jobs(live_store) == []

    def test_picks_up_pending(self, live_store: StoreClient):
        job = create_pending_job("echo", payload={"message": "hi"})
        write_job(live_store, job)
        result = scan_for_claimable_jobs(live_store)
        assert len(result) == 1
        assert result[0].id == job.id

    def test_skips_running(self, live_store: StoreClient):
        job = create_pending_job("echo")
        running = Job(
            **{
                **job.to_frontmatter(),
                "status": STATUS_RUNNING,
                "worker_id": WORKER_ID,
                "claimed_at": now_iso(),
                "updated_at": now_iso(),
            }
        )
        write_job(live_store, running)
        assert scan_for_claimable_jobs(live_store) == []

    def test_skips_succeeded(self, live_store: StoreClient):
        job = create_pending_job("echo")
        done = Job(
            **{
                **job.to_frontmatter(),
                "status": STATUS_SUCCEEDED,
                "result": {"echoed": "hi"},
                "updated_at": now_iso(),
            }
        )
        write_job(live_store, done)
        assert scan_for_claimable_jobs(live_store) == []

    def test_skips_dead(self, live_store: StoreClient):
        job = create_pending_job("echo")
        dead = Job(
            **{
                **job.to_frontmatter(),
                "status": STATUS_DEAD,
                "error": "broken",
                "updated_at": now_iso(),
                "attempts": 3,
            }
        )
        write_job(live_store, dead)
        assert scan_for_claimable_jobs(live_store) == []

    def test_failed_with_ready_backoff_is_claimable(self, live_store: StoreClient):
        job = create_pending_job("echo")
        failed = Job(
            **{
                **job.to_frontmatter(),
                "status": STATUS_FAILED,
                "error": "transient",
                "next_attempt_at": "2020-01-01T00:00:00Z",  # past
                "updated_at": now_iso(),
                "attempts": 1,
            }
        )
        write_job(live_store, failed)
        result = scan_for_claimable_jobs(live_store, now="2026-05-22T10:00:00Z")
        assert len(result) == 1

    def test_failed_with_future_backoff_is_skipped(self, live_store: StoreClient):
        job = create_pending_job("echo")
        failed = Job(
            **{
                **job.to_frontmatter(),
                "status": STATUS_FAILED,
                "error": "transient",
                "next_attempt_at": "2099-01-01T00:00:00Z",  # far future
                "updated_at": now_iso(),
                "attempts": 1,
            }
        )
        write_job(live_store, failed)
        result = scan_for_claimable_jobs(live_store, now="2026-05-22T10:00:00Z")
        assert result == []

    def test_returns_sorted_by_id(self, live_store: StoreClient):
        jobs = []
        for _ in range(3):
            j = create_pending_job("echo")
            write_job(live_store, j)
            jobs.append(j)
        result = scan_for_claimable_jobs(live_store)
        ids = [j.id for j in result]
        assert ids == sorted(ids)


# ======================================================================
# claim
# ======================================================================
class TestClaim:
    def test_pending_to_running_transition(self, live_store: StoreClient):
        job = create_pending_job("echo", payload={"message": "hi"})
        write_job(live_store, job)

        result = claim(live_store, job, WORKER_ID)
        assert result.claimed is True
        assert result.job is not None
        assert result.job.status == STATUS_RUNNING
        assert result.job.worker_id == WORKER_ID
        assert result.job.claimed_at is not None
        assert result.job.attempts == 1  # incremented at claim time

    def test_claim_persists_to_vault(self, live_store: StoreClient):
        job = create_pending_job("echo")
        write_job(live_store, job)

        claim(live_store, job, WORKER_ID)
        reread = read_job(live_store, job.id)
        assert reread.status == STATUS_RUNNING
        assert reread.worker_id == WORKER_ID

    def test_claim_clears_previous_retry_state(self, live_store: StoreClient):
        # Simulate a job that previously failed and is now being re-claimed.
        base = create_pending_job("echo")
        failed = Job(
            **{
                **base.to_frontmatter(),
                "status": STATUS_FAILED,
                "error": "old error",
                "next_attempt_at": "2020-01-01T00:00:00Z",
                "attempts": 1,
                "updated_at": now_iso(),
            }
        )
        write_job(live_store, failed)

        result = claim(live_store, failed, WORKER_ID)
        assert result.claimed is True
        assert result.job.error is None
        assert result.job.next_attempt_at is None
        assert result.job.attempts == 2  # incremented from 1

    def test_claim_increments_attempts(self, live_store: StoreClient):
        job = create_pending_job("echo")
        write_job(live_store, job)
        result = claim(live_store, job, WORKER_ID)
        assert result.job.attempts == job.attempts + 1


# ======================================================================
# execute
# ======================================================================
class TestExecute:
    def test_successful_handler(self):
        job = create_pending_job("echo", payload={"message": "hi"})
        outcome = execute(job)
        assert outcome.result == {"echoed": "hi"}
        assert outcome.error is None
        assert outcome.fatal is False

    def test_unknown_kind_is_fatal(self):
        # Construct a Job with a kind that has no handler.
        job = Job(
            id="x",
            kind="nonexistent-kind",
            status=STATUS_RUNNING,
            created_at="2026-05-22T10:00:00Z",
            updated_at="2026-05-22T10:00:00Z",
            attempts=1,
            max_attempts=3,
            payload={},
        )
        outcome = execute(job)
        assert outcome.result is None
        assert outcome.fatal is True
        assert "nonexistent-kind" in outcome.error

    def test_handler_exception_is_non_fatal(self, isolated_registry):
        def boom(payload):
            raise RuntimeError("kaboom")

        register("boom", boom)
        job = Job(
            id="x",
            kind="boom",
            status=STATUS_RUNNING,
            created_at="2026-05-22T10:00:00Z",
            updated_at="2026-05-22T10:00:00Z",
            attempts=1,
            max_attempts=3,
            payload={},
        )
        outcome = execute(job)
        assert outcome.result is None
        assert outcome.fatal is False
        assert "kaboom" in outcome.error
        assert "RuntimeError" in outcome.error

    def test_handler_returning_non_dict_is_fatal(self, isolated_registry):
        def bad(payload):
            return "not a dict"

        register("bad", bad)
        job = Job(
            id="x",
            kind="bad",
            status=STATUS_RUNNING,
            created_at="2026-05-22T10:00:00Z",
            updated_at="2026-05-22T10:00:00Z",
            attempts=1,
            max_attempts=3,
            payload={},
        )
        outcome = execute(job)
        assert outcome.fatal is True
        assert "expected dict" in outcome.error


# ======================================================================
# resolve
# ======================================================================
class TestResolve:
    def test_success_writes_succeeded(self, live_store: StoreClient):
        job = create_pending_job("echo")
        write_job(live_store, job)
        claimed = claim(live_store, job, WORKER_ID).job

        outcome = ExecutionOutcome(result={"echoed": "hi"}, error=None, fatal=False)
        resolved = resolve(live_store, claimed, outcome)
        assert resolved.status == STATUS_SUCCEEDED
        assert resolved.result == {"echoed": "hi"}
        assert resolved.worker_id is None
        assert resolved.claimed_at is None

    def test_non_fatal_failure_with_retries_left_writes_failed(self, live_store: StoreClient):
        job = create_pending_job("echo", max_attempts=3)
        write_job(live_store, job)
        claimed = claim(live_store, job, WORKER_ID).job  # attempts=1

        outcome = ExecutionOutcome(result=None, error="RuntimeError: boom", fatal=False)
        resolved = resolve(live_store, claimed, outcome)
        assert resolved.status == STATUS_FAILED
        assert resolved.next_attempt_at is not None
        assert resolved.error == "RuntimeError: boom"

    def test_non_fatal_failure_at_max_writes_dead(self, live_store: StoreClient):
        job = create_pending_job("echo", max_attempts=1)
        write_job(live_store, job)
        claimed = claim(live_store, job, WORKER_ID).job  # attempts=1

        outcome = ExecutionOutcome(result=None, error="RuntimeError: boom", fatal=False)
        resolved = resolve(live_store, claimed, outcome)
        assert resolved.status == STATUS_DEAD
        assert resolved.next_attempt_at is None

    def test_fatal_failure_skips_retry_goes_dead(self, live_store: StoreClient):
        # Even with retries available, fatal failures go straight to dead.
        job = create_pending_job("echo", max_attempts=3)
        write_job(live_store, job)
        claimed = claim(live_store, job, WORKER_ID).job  # attempts=1

        outcome = ExecutionOutcome(result=None, error="UnknownJobKind: foo", fatal=True)
        resolved = resolve(live_store, claimed, outcome)
        assert resolved.status == STATUS_DEAD
        assert resolved.next_attempt_at is None

    def test_resolve_persists(self, live_store: StoreClient):
        job = create_pending_job("echo")
        write_job(live_store, job)
        claimed = claim(live_store, job, WORKER_ID).job

        outcome = ExecutionOutcome(result={"echoed": ""}, error=None, fatal=False)
        resolve(live_store, claimed, outcome)
        reread = read_job(live_store, job.id)
        assert reread.status == STATUS_SUCCEEDED


# ======================================================================
# step_once — the full cycle
# ======================================================================
class TestStepOnce:
    def test_empty_vault_returns_none(self, live_store: StoreClient):
        assert step_once(live_store, WORKER_ID) is None

    def test_completes_an_echo_job(self, live_store: StoreClient):
        job = create_pending_job("echo", payload={"message": "hello"})
        write_job(live_store, job)

        resolved = step_once(live_store, WORKER_ID)
        assert resolved is not None
        assert resolved.id == job.id
        assert resolved.status == STATUS_SUCCEEDED
        assert resolved.result == {"echoed": "hello"}

    def test_unknown_kind_goes_dead(self, live_store: StoreClient):
        # Manually write a job with no handler — bypassing
        # create_pending_job's kind validation isn't needed because
        # there's no kind validation in Job itself.
        job = create_pending_job("nonexistent-kind-xyz")
        write_job(live_store, job)

        resolved = step_once(live_store, WORKER_ID)
        assert resolved.status == STATUS_DEAD
        assert "nonexistent-kind-xyz" in resolved.error

    def test_handler_failure_with_retries_left(self, live_store: StoreClient, isolated_registry):
        def flaky(payload):
            raise RuntimeError("transient")

        register("flaky", flaky)
        job = create_pending_job("flaky", max_attempts=3)
        write_job(live_store, job)

        resolved = step_once(live_store, WORKER_ID)
        assert resolved.status == STATUS_FAILED
        assert resolved.next_attempt_at is not None

    def test_picks_only_one_job_per_step(self, live_store: StoreClient):
        # Even with multiple claimable jobs, one step does one job.
        # The loop calls step_once repeatedly to drain.
        for _ in range(3):
            write_job(live_store, create_pending_job("echo"))

        step_once(live_store, WORKER_ID)

        # Two should still be pending.
        from axiom_queue.jobs import list_jobs

        all_ids = list_jobs(live_store)
        statuses = [read_job(live_store, jid).status for jid in all_ids]
        assert statuses.count(STATUS_PENDING) == 2
        assert statuses.count(STATUS_SUCCEEDED) == 1


# ======================================================================
# run_worker — the main loop with stop_event
# ======================================================================
class TestRunWorker:
    def test_stops_immediately_when_stop_event_preset(self, live_store: StoreClient):
        stop = threading.Event()
        stop.set()  # already set
        # Should return immediately without doing any work.
        run_worker(live_store, worker_id=WORKER_ID, stop_event=stop, poll_interval=0.05)

    def test_processes_jobs_until_stop(self, live_store: StoreClient):
        # Seed three jobs, run worker in a thread, stop after a moment.
        for _ in range(3):
            write_job(live_store, create_pending_job("echo", payload={"message": "x"}))

        stop = threading.Event()
        thread = threading.Thread(
            target=run_worker,
            kwargs={
                "client": live_store,
                "worker_id": WORKER_ID,
                "stop_event": stop,
                "poll_interval": 0.05,
            },
            daemon=True,
        )
        thread.start()

        # Wait for all jobs to be processed.
        deadline = time.time() + 5.0
        from axiom_queue.jobs import list_jobs

        while time.time() < deadline:
            all_ids = list_jobs(live_store)
            statuses = [read_job(live_store, jid).status for jid in all_ids]
            if statuses.count(STATUS_SUCCEEDED) == 3:
                break
            time.sleep(0.05)

        stop.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive(), "worker did not exit after stop_event"

        # All three should be succeeded.
        all_ids = list_jobs(live_store)
        statuses = [read_job(live_store, jid).status for jid in all_ids]
        assert statuses.count(STATUS_SUCCEEDED) == 3

    def test_survives_unreadable_job_files(self, live_store: StoreClient, tmp_path: Path):
        # Write a valid job, plus a garbage file directly to disk.
        # The worker should process the valid one and skip the bad one.
        good = create_pending_job("echo", payload={"message": "good"})
        write_job(live_store, good)

        # Drop a corrupt file directly into the vault, bypassing the store.
        # This is a deliberate filesystem-level write — bypassing the
        # store is the whole point: we want to verify the worker is
        # robust to manual / corrupt vault edits.
        corrupt_path = tmp_path / "jobs" / "corrupt.md"
        corrupt_path.write_text("not valid frontmatter at all\n")

        stop = threading.Event()
        thread = threading.Thread(
            target=run_worker,
            kwargs={
                "client": live_store,
                "worker_id": WORKER_ID,
                "stop_event": stop,
                "poll_interval": 0.05,
            },
            daemon=True,
        )
        thread.start()

        deadline = time.time() + 3.0
        while time.time() < deadline:
            try:
                if read_job(live_store, good.id).status == STATUS_SUCCEEDED:
                    break
            except Exception:
                pass
            time.sleep(0.05)

        stop.set()
        thread.join(timeout=2.0)
        assert read_job(live_store, good.id).status == STATUS_SUCCEEDED
