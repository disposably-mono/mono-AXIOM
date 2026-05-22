"""
Watchdog loop for axiom-queue.

Detects jobs stuck in status=running for longer than STALL_THRESHOLD_SECONDS
and reclaims them by writing status=pending. The original worker (if it's
still alive) keeps running and may finish the job; the reclaimed copy is
also eligible for re-execution. Idempotency at the handler level is the
contract that makes this safe.

Concurrency model:
  - Runs in its own thread, parallel to the worker.
  - Scans on a slower cadence than the worker (10s default vs 1s worker).
  - Same single-writer assumption as the worker — Phase 2 has one worker
    and one watchdog total, so no two writers race.

Reclaim rules (locked in Phase 2):
  - status: running → pending (NOT failed). Stall isn't a downstream
    flakiness signal; it's a worker problem. No backoff.
  - attempts: unchanged. The original claim already counted the attempt.
  - worker_id, claimed_at: cleared. They described the now-dead claim.
  - body: appended with a "reclaimed by watchdog" line for vault
    auditability.

Lifecycle: takes a threading.Event for graceful shutdown, same shape
as run_worker. Dispatcher owns the signal handlers.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Iterable

from axiom_queue.ids import now_iso
from axiom_queue.jobs import (
    STATUS_PENDING,
    STATUS_RUNNING,
    Job,
    list_jobs,
    read_job,
)
from axiom_store import StoreClient, parse_frontmatter, render_frontmatter

log = logging.getLogger("axiom_queue.watchdog")

# Phase 2 watchdog parameters. Both locked during the design phase.
STALL_THRESHOLD_SECONDS = 300.0  # 5 minutes
DEFAULT_SCAN_INTERVAL_SECONDS = 10.0


# ----------------------------------------------------------------------
# Time math — pure functions, easy to test
# ----------------------------------------------------------------------
def _parse_iso(ts: str) -> datetime:
    """
    Parse a vault timestamp (YYYY-MM-DDTHH:MM:SSZ) into a UTC datetime.

    The watchdog is the first place we need real arithmetic on timestamps
    (the worker only compares them as strings). Lexicographic comparison
    is sufficient for "is now past next_attempt_at"; computing "how many
    seconds have elapsed since claimed_at" needs actual datetimes.
    """
    # strptime is faster and more permissive about edge cases than fromisoformat
    # for our exact fixed-width format. We accept only the canonical Z form
    # by design — anything else means someone manually edited a vault file
    # with a non-canonical timestamp, which is a fault we want to surface.
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def seconds_since(ts: str, now: str | None = None) -> float:
    """
    Return seconds elapsed between `ts` and `now` (or current time).

    Both timestamps are vault-format ISO strings. Negative results mean
    `ts` is in the future, which is a clock-skew or bad-data condition;
    callers should treat negative as "no stall."
    """
    current = now if now is not None else now_iso()
    return (_parse_iso(current) - _parse_iso(ts)).total_seconds()


def is_stalled(
    job: Job,
    threshold_seconds: float = STALL_THRESHOLD_SECONDS,
    now: str | None = None,
) -> bool:
    """
    Return True if `job` is in running state and has been claimed for
    longer than `threshold_seconds`.

    Defensive: jobs in any other state are never stalled. Jobs missing
    claimed_at while running are anomalous (a worker bug) — we treat
    them as stalled so they get reclaimed and re-evaluated.
    """
    if job.status != STATUS_RUNNING:
        return False
    if job.claimed_at is None:
        # Anomalous state. The worker invariant requires claimed_at
        # whenever status is running. Reclaim defensively.
        log.warning("job %s is running but has no claimed_at", job.id)
        return True

    try:
        elapsed = seconds_since(job.claimed_at, now=now)
    except ValueError as e:
        # Non-canonical timestamp on disk. Treat as stalled — the file
        # is broken anyway, and reclaim might bring it back to a sane state.
        log.warning("job %s has unparseable claimed_at %r: %s", job.id, job.claimed_at, e)
        return True

    if elapsed < 0:
        # Clock skew or future-dated timestamp. Don't reclaim — at worst
        # we'd be reclaiming a job that just started.
        return False
    return elapsed >= threshold_seconds


# ----------------------------------------------------------------------
# Scan for stalled jobs
# ----------------------------------------------------------------------
def scan_for_stalled_jobs(
    client: StoreClient,
    threshold_seconds: float = STALL_THRESHOLD_SECONDS,
    now: str | None = None,
) -> list[Job]:
    """
    Return all jobs that are running and have stalled past the threshold.

    Tolerates corrupt or unreadable job files (logs and skips). The
    watchdog must never crash because someone manually broke a vault file.
    """
    stalled: list[Job] = []
    for job_id in list_jobs(client):
        try:
            job = read_job(client, job_id)
        except FileNotFoundError:
            continue
        except Exception as e:
            log.warning("skipping unreadable job %s: %s", job_id, e)
            continue
        if is_stalled(job, threshold_seconds=threshold_seconds, now=now):
            stalled.append(job)
    return stalled


# ----------------------------------------------------------------------
# Reclaim — running → pending, with body annotation
# ----------------------------------------------------------------------
def _append_reclaim_note(client: StoreClient, job: Job, elapsed: float) -> str:
    """
    Read the existing body of the job file and append a watchdog reclaim
    note. Returns the new body string.

    Body audit trail is one of the Phase 2 watchdog guarantees: the
    vault file itself tells the story of what happened to a job, not
    just the frontmatter.
    """
    # Re-read the raw bytes to get the existing body. We can't reconstruct
    # it from the Job dataclass because the body is freeform Markdown
    # the worker may have customized.
    raw = client.read(f"jobs/{job.id}.md")
    _meta, existing_body = parse_frontmatter(raw.decode("utf-8"))

    minutes = elapsed / 60.0
    note = (
        f"\n> **Reclaimed by watchdog** at {now_iso()} "
        f"after {minutes:.1f}m stall (worker_id={job.worker_id})\n"
    )
    return existing_body + note


def reclaim(client: StoreClient, job: Job) -> Job:
    """
    Reset a stalled running-job back to pending. Clears worker_id and
    claimed_at; preserves attempts so the job doesn't get a free retry.

    Returns the reclaimed Job (now pending). Persists to the vault.
    """
    if job.claimed_at is None:
        elapsed = 0.0
    else:
        try:
            elapsed = max(0.0, seconds_since(job.claimed_at))
        except ValueError:
            elapsed = 0.0

    # Build the new job state.
    reclaimed = Job(
        id=job.id,
        kind=job.kind,
        status=STATUS_PENDING,
        created_at=job.created_at,
        updated_at=now_iso(),
        attempts=job.attempts,  # unchanged — the attempt counted
        max_attempts=job.max_attempts,
        payload=job.payload,
        result=None,
        error=None,
        next_attempt_at=None,
        worker_id=None,
        claimed_at=None,
        tags=job.tags,
    )

    # Body: append the reclaim note to whatever body was already there.
    new_body = _append_reclaim_note(client, job, elapsed)

    # Write the assembled file directly through the store. We can't use
    # write_job because it regenerates the body from scratch — we want
    # to preserve the existing body and append.
    text = render_frontmatter(reclaimed.to_frontmatter(), new_body)
    client.write(f"jobs/{job.id}.md", text.encode("utf-8"))

    log.info(
        "reclaimed stalled job %s (was claimed by %s, stalled %.1fs)",
        job.id,
        job.worker_id,
        elapsed,
    )
    return reclaimed


# ----------------------------------------------------------------------
# One cycle of the watchdog loop
# ----------------------------------------------------------------------
def step_once(
    client: StoreClient,
    threshold_seconds: float = STALL_THRESHOLD_SECONDS,
) -> list[Job]:
    """
    Scan and reclaim all stalled jobs. Returns the list of jobs reclaimed
    this tick. Exposed so tests can drive the watchdog one tick at a time.
    """
    stalled = scan_for_stalled_jobs(client, threshold_seconds=threshold_seconds)
    reclaimed: list[Job] = []
    for job in stalled:
        try:
            reclaimed.append(reclaim(client, job))
        except Exception as e:  # noqa: BLE001
            # A failed reclaim is logged and skipped. The next scan
            # will try again. We don't want one bad job to stop the
            # watchdog from servicing others.
            log.exception("failed to reclaim job %s: %s", job.id, e)
    return reclaimed


# ----------------------------------------------------------------------
# The main loop
# ----------------------------------------------------------------------
def run_watchdog(
    client: StoreClient,
    stop_event: threading.Event | None = None,
    scan_interval: float = DEFAULT_SCAN_INTERVAL_SECONDS,
    threshold_seconds: float = STALL_THRESHOLD_SECONDS,
) -> None:
    """
    Run the watchdog loop until stop_event is set.

    Same lifecycle shape as run_worker: checks the event at the top of
    each iteration, sleeps in scan_interval-second chunks that wake
    early on the event.
    """
    stop_event = stop_event or threading.Event()
    log.info(
        "watchdog starting (scan=%ss, stall_threshold=%ss)",
        scan_interval,
        threshold_seconds,
    )
    try:
        while not stop_event.is_set():
            try:
                step_once(client, threshold_seconds=threshold_seconds)
            except Exception as e:  # noqa: BLE001
                # Safety net — the loop must not die because of a
                # transient transport error or store unavailability.
                log.exception("unexpected error in watchdog step: %s", e)
            stop_event.wait(timeout=scan_interval)
    finally:
        log.info("watchdog exiting")
