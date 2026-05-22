"""
Tests for axiom-queue.jobs.

Strategy:
  - Job constructor/validation: pure, no I/O, no StoreClient.
  - to_frontmatter / from_frontmatter: pure roundtrips.
  - create_pending_job: pure, but monkeypatches ids module for
    deterministic timestamps and IDs.
  - write_job / read_job / list_jobs: real StoreClient against a real
    axiom-store server bound to a temp vault, via axiom_store.test_utils.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from axiom_queue import jobs
from axiom_queue.jobs import (
    DEFAULT_MAX_ATTEMPTS,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    Job,
    JobValidationError,
    create_pending_job,
    list_jobs,
    read_job,
    write_job,
)
from axiom_store import StoreClient
from axiom_store.test_utils import LocalServer


# ----------------------------------------------------------------------
# Sample frontmatter helpers
# ----------------------------------------------------------------------
def _minimal_pending_md(
    id_: str = "test-id-1",
    kind: str = "echo",
    payload: dict | None = None,
) -> dict:
    return {
        "id": id_,
        "kind": kind,
        "status": STATUS_PENDING,
        "created_at": "2026-05-22T10:00:00Z",
        "updated_at": "2026-05-22T10:00:00Z",
        "attempts": 0,
        "max_attempts": 3,
        "payload": payload or {"message": "hi"},
    }


# ======================================================================
# Job dataclass construction + validation
# ======================================================================
class TestJobConstruction:
    def test_minimal_pending_job_valid(self):
        job = Job(**_minimal_pending_md())
        assert job.status == STATUS_PENDING
        assert job.attempts == 0
        assert job.result is None

    def test_all_optional_fields(self):
        md = _minimal_pending_md()
        md["status"] = STATUS_SUCCEEDED
        md["result"] = {"echoed": "hi"}
        md["worker_id"] = "worker-1"
        md["claimed_at"] = "2026-05-22T10:00:01Z"
        md["tags"] = ["self-test"]
        job = Job(**md)
        assert job.result == {"echoed": "hi"}
        assert job.worker_id == "worker-1"
        assert job.tags == ["self-test"]

    def test_unknown_status_rejected(self):
        md = _minimal_pending_md()
        md["status"] = "QUEUED"
        with pytest.raises(JobValidationError, match="unknown status"):
            Job(**md)

    def test_missing_required_field_rejected(self):
        md = _minimal_pending_md()
        del md["id"]
        with pytest.raises(TypeError):
            # TypeError from dataclass — callers normally use
            # from_frontmatter which translates this. Direct construction
            # exposes the raw dataclass behavior, which is fine.
            Job(**md)

    def test_wrong_type_for_payload_rejected(self):
        md = _minimal_pending_md()
        md["payload"] = "not a dict"
        with pytest.raises(JobValidationError, match="payload"):
            Job(**md)

    def test_wrong_type_for_attempts_rejected(self):
        md = _minimal_pending_md()
        md["attempts"] = "0"
        with pytest.raises(JobValidationError, match="attempts"):
            Job(**md)


# ======================================================================
# Frontmatter roundtrip
# ======================================================================
class TestFrontmatterRoundtrip:
    def test_pending_job_roundtrip(self):
        original = Job(**_minimal_pending_md())
        md = original.to_frontmatter()
        rebuilt = Job.from_frontmatter(md)
        assert rebuilt == original

    def test_succeeded_job_roundtrip(self):
        md = _minimal_pending_md()
        md["status"] = STATUS_SUCCEEDED
        md["result"] = {"echoed": "hi"}
        md["worker_id"] = "worker-1"
        md["claimed_at"] = "2026-05-22T10:00:01Z"
        original = Job(**md)
        rebuilt = Job.from_frontmatter(original.to_frontmatter())
        assert rebuilt == original

    def test_optional_fields_with_none_omitted_from_frontmatter(self):
        job = Job(**_minimal_pending_md())
        md = job.to_frontmatter()
        # None-valued optionals should not appear
        for key in ("result", "error", "next_attempt_at", "worker_id", "claimed_at", "tags"):
            assert key not in md, f"{key} should be omitted when None"

    def test_from_frontmatter_rejects_unknown_keys(self):
        md = _minimal_pending_md()
        md["bogus_extra"] = "nope"
        with pytest.raises(JobValidationError, match="unknown keys"):
            Job.from_frontmatter(md)

    def test_from_frontmatter_rejects_non_dict(self):
        with pytest.raises(JobValidationError, match="must be a dict"):
            Job.from_frontmatter("not a dict")  # type: ignore[arg-type]

    def test_from_frontmatter_missing_required(self):
        md = _minimal_pending_md()
        del md["id"]
        with pytest.raises(JobValidationError):
            Job.from_frontmatter(md)


# ======================================================================
# create_pending_job factory
# ======================================================================
class TestCreatePendingJob:
    def test_basic(self, monkeypatch):
        monkeypatch.setattr(jobs, "new_job_id", lambda: "fixed-id")
        monkeypatch.setattr(jobs, "now_iso", lambda: "2026-05-22T10:00:00Z")
        job = create_pending_job("echo", payload={"message": "hi"})
        assert job.id == "fixed-id"
        assert job.status == STATUS_PENDING
        assert job.created_at == job.updated_at == "2026-05-22T10:00:00Z"
        assert job.attempts == 0
        assert job.max_attempts == DEFAULT_MAX_ATTEMPTS
        assert job.payload == {"message": "hi"}

    def test_default_payload_is_empty_dict(self, monkeypatch):
        monkeypatch.setattr(jobs, "new_job_id", lambda: "fixed-id")
        monkeypatch.setattr(jobs, "now_iso", lambda: "2026-05-22T10:00:00Z")
        job = create_pending_job("noop")
        assert job.payload == {}

    def test_custom_max_attempts(self, monkeypatch):
        monkeypatch.setattr(jobs, "new_job_id", lambda: "fixed-id")
        monkeypatch.setattr(jobs, "now_iso", lambda: "2026-05-22T10:00:00Z")
        job = create_pending_job("echo", max_attempts=5)
        assert job.max_attempts == 5

    def test_ids_are_unique_in_real_use(self):
        # Sanity check without monkeypatch.
        a = create_pending_job("echo")
        b = create_pending_job("echo")
        assert a.id != b.id


# ======================================================================
# Live server fixture — reuses axiom_store.test_utils.LocalServer
# ======================================================================
@pytest.fixture
def live_store(tmp_path: Path):
    """
    Spin up a real axiom-store server on an ephemeral port, bound to
    tmp_path as the vault root. Yields a StoreClient.

    Reuses LocalServer from axiom_store.test_utils so we have exactly
    one way to start a test server in this repo. If the server pattern
    ever changes, this fixture changes with it.
    """
    # The vault needs jobs/ to exist for list_dir on an empty directory
    # (axiom-store treats a missing directory as NOT_FOUND).
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)

    server = LocalServer(tmp_path).start()
    client = StoreClient(host=server.host, port=server.port)
    try:
        yield client
    finally:
        server.stop()


# ======================================================================
# write_job / read_job / list_jobs against live server
# ======================================================================
class TestStoreIO:
    def test_write_and_read_roundtrip(self, live_store: StoreClient):
        job = create_pending_job("echo", payload={"message": "hi"})
        write_job(live_store, job)
        rebuilt = read_job(live_store, job.id)
        assert rebuilt == job

    def test_list_jobs_empty(self, live_store: StoreClient):
        assert list_jobs(live_store) == []

    def test_list_jobs_after_writes(self, live_store: StoreClient):
        ids = []
        for _ in range(3):
            job = create_pending_job("echo")
            write_job(live_store, job)
            ids.append(job.id)
        assert sorted(list_jobs(live_store)) == sorted(ids)

    def test_list_jobs_ignores_scaffold_readme_on_disk(self, tmp_path: Path):
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / "README.md").write_text("# jobs/\n", encoding="utf-8")

        server = LocalServer(tmp_path).start()
        client = StoreClient(host=server.host, port=server.port)
        try:
            assert list_jobs(client) == []
        finally:
            server.stop()

    def test_read_missing_job_raises(self, live_store: StoreClient):
        with pytest.raises(FileNotFoundError):
            read_job(live_store, "does-not-exist")

    def test_write_then_overwrite_with_new_status(self, live_store: StoreClient):
        job = create_pending_job("echo", payload={"message": "hi"})
        write_job(live_store, job)
        # Simulate a worker claiming the job.
        claimed = Job(
            **{
                **job.to_frontmatter(),
                "status": STATUS_RUNNING,
                "worker_id": "worker-1",
                "claimed_at": "2026-05-22T10:00:01Z",
                "updated_at": "2026-05-22T10:00:01Z",
            }
        )
        write_job(live_store, claimed)
        rebuilt = read_job(live_store, job.id)
        assert rebuilt.status == STATUS_RUNNING
        assert rebuilt.worker_id == "worker-1"

    def test_write_invalid_payload_raises_before_store_call(self):
        """A Job that fails its own __post_init__ never reaches the
        store. Schema validation happens twice (Job, then store) which
        is intentional — defense in depth."""
        with pytest.raises(JobValidationError):
            Job(
                id="x",
                kind="echo",
                status=STATUS_PENDING,
                created_at="2026-05-22T10:00:00Z",
                updated_at="2026-05-22T10:00:00Z",
                attempts=0,
                max_attempts=3,
                payload="not a dict",  # type: ignore[arg-type]
            )
