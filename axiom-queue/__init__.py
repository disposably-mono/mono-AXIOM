"""
axiom-queue — job dispatch and worker management.

Layer 2 of mono-AXIOM. Jobs are `.md` files in `mono-vault/jobs/`,
written and read through `axiom-store`. Workers are separate processes
that poll, claim, execute, and write results back. A watchdog reclaims
stalled jobs.

Public surface grows as the layer fills in. Phase 2 currently provides
the data layer (jobs), retry policy (retry), the handler registry
(handlers), the worker loop (worker), the watchdog (watchdog), and the
dispatcher (dispatcher).
"""

from importlib import import_module

from axiom_queue.handlers import (
    HANDLERS,
    Handler,
    HandlerError,
    UnknownJobKind,
    dispatch,
    echo_handler,
    noop_handler,
    register,
    unregister,
)
from axiom_queue.jobs import (
    Job,
    JobValidationError,
    create_pending_job,
    list_jobs,
    read_job,
    write_job,
)
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
from axiom_queue.watchdog import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    STALL_THRESHOLD_SECONDS,
    is_stalled,
    reclaim,
    run_watchdog,
    scan_for_stalled_jobs,
    seconds_since,
)
from axiom_queue.worker import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    ClaimResult,
    ExecutionOutcome,
    claim,
    execute,
    make_worker_id,
    resolve,
    run_worker,
    scan_for_claimable_jobs,
)

_DISPATCHER_EXPORTS = frozenset(
    {
        "DEFAULT_HOST",
        "DEFAULT_JOIN_TIMEOUT_SECONDS",
        "DEFAULT_PIDFILE_NAME",
        "DEFAULT_PORT",
        "DispatcherAlreadyRunning",
        "QueueService",
        "acquire_pidfile",
        "default_pidfile_path",
        "install_signal_handlers",
        "is_process_alive",
        "read_pidfile",
        "release_pidfile",
        "run_dispatcher",
        "start_queue_service",
        "stop_queue_service",
    }
)


def __getattr__(name: str):
    """Lazy-load dispatcher exports so `python -m axiom_queue.dispatcher` is clean."""
    if name in _DISPATCHER_EXPORTS:
        dispatcher = import_module("axiom_queue.dispatcher")
        return getattr(dispatcher, name)
    raise AttributeError(f"module 'axiom_queue' has no attribute {name!r}")


__all__ = [
    "BASE_DELAY_SECONDS",
    "ClaimResult",
    "DEFAULT_HOST",
    "DEFAULT_JOIN_TIMEOUT_SECONDS",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_PIDFILE_NAME",
    "DEFAULT_PORT",
    "DEFAULT_SCAN_INTERVAL_SECONDS",
    "ExecutionOutcome",
    "HANDLERS",
    "Handler",
    "HandlerError",
    "JITTER_FRACTION",
    "Job",
    "JobValidationError",
    "MAX_DELAY_SECONDS",
    "QueueService",
    "RetryDecision",
    "STALL_THRESHOLD_SECONDS",
    "DispatcherAlreadyRunning",
    "UnknownJobKind",
    "acquire_pidfile",
    "claim",
    "compute_backoff",
    "create_pending_job",
    "decide_after_failure",
    "decide_after_success",
    "default_pidfile_path",
    "dispatch",
    "echo_handler",
    "execute",
    "install_signal_handlers",
    "is_process_alive",
    "is_ready_to_retry",
    "is_stalled",
    "list_jobs",
    "make_worker_id",
    "noop_handler",
    "read_job",
    "reclaim",
    "register",
    "resolve",
    "read_pidfile",
    "release_pidfile",
    "run_dispatcher",
    "run_watchdog",
    "run_worker",
    "scan_for_claimable_jobs",
    "scan_for_stalled_jobs",
    "seconds_since",
    "start_queue_service",
    "stop_queue_service",
    "unregister",
    "write_job",
]
