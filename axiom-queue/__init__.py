"""
axiom-queue — job dispatch and worker management.

Layer 2 of mono-AXIOM. Jobs are `.md` files in `mono-vault/jobs/`,
written and read through `axiom-store`. Workers are separate processes
that poll, claim, execute, and write results back. A watchdog reclaims
stalled jobs.

Public surface grows as the layer fills in. Phase 2 currently provides
the data layer (jobs), retry policy (retry), and the handler registry
(handlers).
"""

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

__all__ = [
    "BASE_DELAY_SECONDS",
    "HANDLERS",
    "Handler",
    "HandlerError",
    "JITTER_FRACTION",
    "Job",
    "JobValidationError",
    "MAX_DELAY_SECONDS",
    "RetryDecision",
    "UnknownJobKind",
    "compute_backoff",
    "create_pending_job",
    "decide_after_failure",
    "decide_after_success",
    "dispatch",
    "echo_handler",
    "is_ready_to_retry",
    "list_jobs",
    "noop_handler",
    "read_job",
    "register",
    "unregister",
    "write_job",
]

