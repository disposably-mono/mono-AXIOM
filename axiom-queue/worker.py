"""
Worker loop for axiom-queue.

A worker is a long-running process that polls mono-vault/jobs/ for
pending work, claims a job, executes its handler, and writes the
result back. Each step is a pure-ish function that takes a StoreClient
and operates on the vault — easy to test in isolation. The main loop
is just orchestration.

Concurrency model: this module assumes a SINGLE worker per vault.
Multi-worker support requires atomic claim semantics (rename-based, or
fcntl locking) that aren't in Phase 2. The dispatcher enforces
single-worker via a pidfile in XDG cache.

Lifecycle: the worker takes a stop_event (threading.Event) from its
caller. The dispatcher installs signal handlers that set the event;
the worker checks the event at the top of each loop iteration. A
job already in flight always finishes before exit — we'd rather wait
than corrupt state.

Worker identity: f"worker-{os.getpid()}". Written to claimed jobs in
the `worker_id` field. Used in logs and (eventually) by the watchdog
to detect which worker abandoned a stalled job.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from axiom_queue.handlers import HandlerError, UnknownJobKind, dispatch
from axiom_queue.ids import now_iso
from axiom_queue.jobs import (
    STATUS_PENDING,
    STATUS_RUNNING,
    Job,
    list_jobs,
    read_job,
    write_job,
)
from axiom_queue.retry import (
    decide_after_failure,
    decide_after_success,
    is_ready_to_retry,
)
from axiom_store import StoreClient

log = logging.getLogger("axiom_queue.worker")

# Poll interval when no claimable jobs are found. Locked at 1s.
DEFAULT_POLL_INTERVAL_SECONDS = 1.0


def make_worker_id() -> str:
    """Stable identity for this worker process. Logged with each
    transition; written to claimed jobs in worker_id."""
    return f"worker-{os.getpid()}"


# ----------------------------------------------------------------------
# Step 1: SCAN — find jobs the worker is allowed to pick up.
# ----------------------------------------------------------------------
def scan_for_claimable_jobs(
    client: StoreClient,
    now: str | None = None,
) -> list[Job]:
    """
    Return all jobs eligible for claiming, in lexical id order.

    A job is claimable iff:
      - status is "pending"   (initial submission)
      - status is "failed" AND its next_attempt_at has passed (retry ready)

    Jobs in running/succeeded/dead are skipped. Jobs whose backoff
    hasn't expired are skipped.

    Reads are tolerant of corrupt or unparseable job files: they are
    logged and skipped, not allowed to crash the worker.
    """
    claimable: list[Job] = []
    job_ids = list_jobs(client)

    for job_id in job_ids:
        try:
            job = read_job(client, job_id)
        except FileNotFoundError:
            # Job vanished between list and read — race with delete,
            # tolerable; just skip.
            continue
        except Exception as e:
            log.warning("skipping unreadable job %s: %s", job_id, e)
            continue

        if job.status == STATUS_PENDING:
            claimable.append(job)
        elif job.status == "failed":
            if is_ready_to_retry(job.next_attempt_at, now=now):
                claimable.append(job)

    return claimable


# ----------------------------------------------------------------------
# Step 2: CLAIM — transition pending/failed → running.
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class ClaimResult:
    """Outcome of attempting to claim a job."""

    claimed: bool
    job: Job | None  # the running-state job, if claimed
    reason: str | None  # if not claimed, why


def claim(client: StoreClient, job: Job, worker_id: str) -> ClaimResult:
    """
    Attempt to claim `job` by writing it back as running. Returns the
    updated Job (now in running state) on success.

    With a single-worker design, this is a straight write. If we ever
    go multi-worker, this is where the atomic-rename or compare-and-set
    logic lives.

    The attempts counter is incremented HERE, before the handler runs.
    Rationale: if the worker crashes mid-handler, the counter on disk
    already reflects the attempt — the watchdog won't accidentally
    grant an extra retry. This is the standard "attempts means tries
    started" convention.
    """
    now = now_iso()
    claimed_job = Job(
        id=job.id,
        kind=job.kind,
        status=STATUS_RUNNING,
        created_at=job.created_at,
        updated_at=now,
        attempts=job.attempts + 1,
        max_attempts=job.max_attempts,
        payload=job.payload,
        # Clear retry-related state from the previous attempt.
        result=None,
        error=None,
        next_attempt_at=None,
        worker_id=worker_id,
        claimed_at=now,
        tags=job.tags,
    )
    try:
        write_job(client, claimed_job)
    except Exception as e:
        # Write failed (transport issue, schema validation drift, etc).
        # Don't crash the worker; let the next loop iteration retry.
        log.warning("claim write failed for job %s: %s", job.id, e)
        return ClaimResult(claimed=False, job=None, reason=f"write failed: {e}")

    log.info(
        "claimed job %s (kind=%s, attempt=%d/%d)",
        job.id,
        job.kind,
        claimed_job.attempts,
        claimed_job.max_attempts,
    )
    return ClaimResult(claimed=True, job=claimed_job, reason=None)


# ----------------------------------------------------------------------
# Step 3: EXECUTE — run the handler. Returns (result, error).
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class ExecutionOutcome:
    """Outcome of running a handler. Exactly one of result/error is set."""

    result: dict[str, Any] | None
    error: str | None
    # True if the failure is fatal (UnknownJobKind, HandlerError).
    # Fatal failures bypass retry and go straight to dead.
    fatal: bool


def execute(job: Job) -> ExecutionOutcome:
    """
    Run the handler for `job.kind` against `job.payload`. Catches
    everything — the worker must not crash because a handler raised.

    Three outcome shapes:
      1. Handler returned a dict          → result set, error None,    fatal False
      2. Handler raised (ordinary failure) → result None, error set,   fatal False
      3. Handler contract violation        → result None, error set,   fatal True
         (UnknownJobKind, HandlerError — no point retrying)
    """
    try:
        result = dispatch(job.kind, job.payload)
        return ExecutionOutcome(result=result, error=None, fatal=False)
    except UnknownJobKind as e:
        log.error("fatal: %s", e)
        return ExecutionOutcome(result=None, error=str(e), fatal=True)
    except HandlerError as e:
        log.error("fatal: handler %s violated contract: %s", job.kind, e)
        return ExecutionOutcome(result=None, error=str(e), fatal=True)
    except Exception as e:  # noqa: BLE001
        # Ordinary handler failure. Eligible for retry.
        log.warning("job %s failed (attempt %d): %s", job.id, job.attempts, e)
        return ExecutionOutcome(
            result=None,
            error=f"{type(e).__name__}: {e}",
            fatal=False,
        )


# ----------------------------------------------------------------------
# Step 4: RESOLVE — write the final state for this attempt.
# ----------------------------------------------------------------------
def resolve(
    client: StoreClient,
    job: Job,
    outcome: ExecutionOutcome,
) -> Job:
    """
    Translate the execution outcome into a state transition and write
    the new job state back to the vault. Returns the final Job.
    """
    if outcome.result is not None:
        decision = decide_after_success()
        result_field = outcome.result
        error_field = None
    else:
        if outcome.fatal:
            # Fatal failures skip retry — straight to dead.
            from axiom_queue.jobs import STATUS_DEAD
            from axiom_queue.retry import RetryDecision

            decision = RetryDecision(
                next_status=STATUS_DEAD,
                next_attempt_at=None,
                delay_seconds=0.0,
            )
        else:
            decision = decide_after_failure(
                attempts=job.attempts,
                max_attempts=job.max_attempts,
            )
        result_field = None
        error_field = outcome.error

    now = now_iso()
    resolved = Job(
        id=job.id,
        kind=job.kind,
        status=decision.next_status,
        created_at=job.created_at,
        updated_at=now,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        payload=job.payload,
        result=result_field,
        error=error_field,
        next_attempt_at=decision.next_attempt_at,
        # worker_id/claimed_at cleared when leaving running state — they
        # only meaningfully describe the most recent execution attempt
        # while it was in flight.
        worker_id=None,
        claimed_at=None,
        tags=job.tags,
    )
    write_job(client, resolved)

    log.info(
        "resolved job %s: %s → %s%s",
        job.id,
        job.status,
        resolved.status,
        f" (next_attempt_at={resolved.next_attempt_at})" if resolved.next_attempt_at else "",
    )
    return resolved


# ----------------------------------------------------------------------
# Step 5: One full cycle of the loop.
# ----------------------------------------------------------------------
def step_once(
    client: StoreClient,
    worker_id: str,
) -> Job | None:
    """
    Run one scan/claim/execute/resolve cycle. Returns the resolved Job
    if work happened, or None if there was nothing to do.

    Exposed for testing — tests can drive the worker one tick at a
    time without spawning a thread.
    """
    claimable = scan_for_claimable_jobs(client)
    if not claimable:
        return None

    # Process the lexically-first claimable job. With a single worker
    # this is deterministic; with multi-worker, the claim race would
    # need to be resolved here.
    target = claimable[0]
    claim_result = claim(client, target, worker_id)
    if not claim_result.claimed:
        return None
    running = claim_result.job
    assert running is not None  # guaranteed by claim_result.claimed

    outcome = execute(running)
    return resolve(client, running, outcome)


# ----------------------------------------------------------------------
# The main loop.
# ----------------------------------------------------------------------
def run_worker(
    client: StoreClient,
    worker_id: str | None = None,
    stop_event: threading.Event | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    """
    Run the worker loop until stop_event is set.

    Lifecycle contract:
      - The loop checks stop_event at the TOP of each iteration.
      - A job already in flight always finishes before the next check.
      - When idle, the loop sleeps in `poll_interval`-second chunks
        but wakes early if stop_event fires.

    Args:
        client: a connected StoreClient pointed at the vault.
        worker_id: this worker's identity string. Defaults to
            make_worker_id(); injectable for tests.
        stop_event: threading.Event the caller sets to request shutdown.
            If None, the loop runs forever (only useful in tests with
            tight bounded iteration).
        poll_interval: seconds to sleep between scans when idle.
    """
    worker_id = worker_id or make_worker_id()
    stop_event = stop_event or threading.Event()

    log.info("worker %s starting (poll=%ss)", worker_id, poll_interval)
    try:
        while not stop_event.is_set():
            try:
                resolved = step_once(client, worker_id)
            except Exception as e:  # noqa: BLE001
                # Last-resort safety net: a bug in step_once itself
                # must not kill the worker. Log and continue.
                log.exception("unexpected error in worker step: %s", e)
                resolved = None

            if resolved is None:
                # Idle. Sleep in a way that wakes early on stop_event.
                stop_event.wait(timeout=poll_interval)
            # If we did work, loop immediately — there may be more.
    finally:
        log.info("worker %s exiting", worker_id)
