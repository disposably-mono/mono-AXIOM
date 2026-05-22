"""
Data layer for axiom-queue jobs.

A `Job` is the in-memory representation of a job file in
`mono-vault/jobs/<id>.md`. The dataclass mirrors the JOB schema in
axiom-store/schema.py exactly — required fields are dataclass fields
with no defaults, optional fields default to None.

This module owns:
  - the Job dataclass and its frontmatter conversion
  - the create_pending_job factory
  - read/write/list helpers that go through StoreClient

It does NOT own:
  - state transition rules (worker.py and watchdog.py enforce those)
  - the body Markdown narrative beyond a minimal template

All schema validation happens inside Job — you cannot construct an
invalid Job in memory. The store validates again on write, giving us
defense in depth.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from axiom_queue.ids import new_job_id, now_iso
from axiom_store import (
    JOB,
    SchemaError,
    StoreClient,
    parse_frontmatter,
    render_frontmatter,
    schema_for,
    validate,
)

# Status vocabulary. Keep in sync with the state machine in PRD.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_DEAD = "dead"

ALL_STATUSES = frozenset(
    {STATUS_PENDING, STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED, STATUS_DEAD}
)

DEFAULT_MAX_ATTEMPTS = 3


class JobValidationError(ValueError):
    """Raised when a Job cannot be constructed from invalid input."""


@dataclass(frozen=True)
class Job:
    """
    In-memory representation of a job file in mono-vault/jobs/<id>.md.

    Required fields mirror the JOB schema's required keys.
    Optional fields default to None and are omitted from frontmatter
    when not set.
    """

    # Required
    id: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    attempts: int
    max_attempts: int
    payload: dict[str, Any] = field(default_factory=dict)

    # Optional
    result: dict[str, Any] | None = None
    error: str | None = None
    next_attempt_at: str | None = None
    worker_id: str | None = None
    claimed_at: str | None = None
    tags: list[str] | None = None

    def __post_init__(self) -> None:
        # Defensive: status must be in the known vocabulary.
        if self.status not in ALL_STATUSES:
            raise JobValidationError(
                f"unknown status {self.status!r}; must be one of {sorted(ALL_STATUSES)}"
            )
        # Validate against the JOB schema. This is the single source of
        # truth — if the schema changes, Job validation tracks it
        # automatically.
        try:
            validate(self.to_frontmatter(), JOB)
        except SchemaError as e:
            raise JobValidationError(str(e)) from e

    # ------------------------------------------------------------------
    # Frontmatter conversion
    # ------------------------------------------------------------------
    def to_frontmatter(self) -> dict[str, Any]:
        """Return the dict that should be YAML-serialized to frontmatter.

        Optional fields with value None are omitted entirely (rather
        than rendered as `key: null`) so the file stays minimal and
        human-readable in Obsidian.
        """
        md: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "payload": self.payload,
        }
        # Optional fields: include only when set.
        for key in (
            "result",
            "error",
            "next_attempt_at",
            "worker_id",
            "claimed_at",
            "tags",
        ):
            value = getattr(self, key)
            if value is not None:
                md[key] = value
        return md

    @classmethod
    def from_frontmatter(cls, md: dict[str, Any]) -> Job:
        """Construct a Job from a frontmatter dict. Validates."""
        if not isinstance(md, dict):
            raise JobValidationError(f"frontmatter must be a dict, got {type(md).__name__}")

        known_keys = {f.name for f in fields(cls)}
        unknown = set(md) - known_keys
        if unknown:
            raise JobValidationError(f"unknown keys in frontmatter: {sorted(unknown)}")

        # Pull keys present in md, let the dataclass apply its own
        # defaults for absent optional ones. __post_init__ revalidates.
        try:
            return cls(**md)
        except TypeError as e:
            # Missing required arg — convert to JobValidationError so
            # callers see a consistent exception type.
            raise JobValidationError(str(e)) from e


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------
def create_pending_job(
    kind: str,
    payload: dict[str, Any] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Job:
    """
    Build a fresh pending Job. Generates a new UUID and timestamps.

    The returned Job is in memory only — it has not been written to
    the vault. Call write_job(client, job) to persist.
    """
    now = now_iso()
    return Job(
        id=new_job_id(),
        kind=kind,
        status=STATUS_PENDING,
        created_at=now,
        updated_at=now,
        attempts=0,
        max_attempts=max_attempts,
        payload=payload or {},
    )


# ----------------------------------------------------------------------
# Body rendering — minimal, human-readable
# ----------------------------------------------------------------------
def _render_body(job: Job) -> str:
    """Default Markdown body. Workers may overwrite this with richer
    content; this is just enough to be readable in Obsidian."""
    if job.status == STATUS_SUCCEEDED:
        latest = f"result: {job.result!r}"
    elif job.status in (STATUS_FAILED, STATUS_DEAD):
        latest = f"error: {job.error or '(none)'}"
    else:
        latest = job.status
    return (
        f"## Job: {job.kind}\n\n"
        f"- Created: {job.created_at}\n"
        f"- Attempts: {job.attempts}/{job.max_attempts}\n\n"
        f"### Latest result\n{latest}\n"
    )


# ----------------------------------------------------------------------
# StoreClient I/O
# ----------------------------------------------------------------------
def _job_path(job_id: str) -> str:
    return f"jobs/{job_id}.md"


def write_job(client: StoreClient, job: Job) -> None:
    """Render job to Markdown and write through the store. Raises if
    the store rejects (schema, path, or transport errors propagate)."""
    # Sanity: confirm the path will route to the JOB schema. This
    # protects against the registry being misconfigured at runtime.
    if schema_for(_job_path(job.id)) is not JOB:
        raise JobValidationError(
            "schema registry does not route 'jobs/' to JOB — axiom-store/schema.py is misconfigured"
        )
    text = render_frontmatter(job.to_frontmatter(), _render_body(job))
    client.write(_job_path(job.id), text.encode("utf-8"))


def read_job(client: StoreClient, job_id: str) -> Job:
    """Read jobs/<id>.md and parse it back into a Job. Raises
    FileNotFoundError (from StoreClient) if the job doesn't exist."""
    raw = client.read(_job_path(job_id))
    text = raw.decode("utf-8")
    metadata, _body = parse_frontmatter(text)
    return Job.from_frontmatter(metadata)


def list_jobs(client: StoreClient) -> list[str]:
    """Return job IDs (filenames in jobs/ minus the .md suffix), sorted.

    Files not ending in .md are skipped. The scaffold README is also
    skipped — it is documentation, not a job file.
    """
    filenames = client.list_dir("jobs/")
    return sorted(
        name[:-3] for name in filenames if name.endswith(".md") and name != "README.md"
    )
