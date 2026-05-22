"""Tests for axiom_store.schema."""

import pytest

from axiom_store.schema import (
    FACT,
    JOB,
    Schema,
    SchemaError,
    schema_for,
    validate,
)


# ---------------------------------------------------------------------------
# Registry lookup
# ---------------------------------------------------------------------------


def test_schema_for_fact_path():
    assert schema_for("memory/facts/x.md") is FACT


def test_schema_for_job_path():
    assert schema_for("jobs/abc.md") is JOB


def test_schema_for_unknown_path_returns_none():
    assert schema_for("system/PRD.md") is None
    assert schema_for("fetch/uploads/file.md") is None
    assert schema_for("exports/dump.md") is None


def test_schema_for_root_path_returns_none():
    assert schema_for("anything.md") is None


# ---------------------------------------------------------------------------
# validate() success cases
# ---------------------------------------------------------------------------


def test_validate_minimal_fact_ok():
    validate(
        {"type": "fact", "created": "2026-05-21"},
        FACT,
    )


def test_validate_fact_with_optional_ok():
    validate(
        {
            "type": "fact",
            "created": "2026-05-21",
            "tags": ["python", "gil"],
            "source": "https://example.com",
        },
        FACT,
    )


# ---------------------------------------------------------------------------
# validate() failure cases
# ---------------------------------------------------------------------------


def test_validate_missing_required_raises():
    with pytest.raises(SchemaError, match="missing required key 'created'"):
        validate({"type": "fact"}, FACT)


def test_validate_wrong_type_for_required_raises():
    with pytest.raises(SchemaError, match="must be str"):
        validate({"type": "fact", "created": 12345}, FACT)


def test_validate_wrong_type_for_optional_raises():
    with pytest.raises(SchemaError, match="must be list"):
        validate(
            {"type": "fact", "created": "2026-05-21", "tags": "not-a-list"},
            FACT,
        )


def test_validate_extra_key_raises_by_default():
    with pytest.raises(SchemaError, match="unexpected keys"):
        validate(
            {"type": "fact", "created": "2026-05-21", "weird": "value"},
            FACT,
        )


def test_validate_allow_extra_permits_unknown_keys():
    permissive = Schema(
        required={"type": str},
        optional={},
        allow_extra=True,
    )
    validate({"type": "x", "anything": 42, "else": []}, permissive)


def test_validate_non_dict_raises():
    with pytest.raises(SchemaError, match="must be a dict"):
        validate(["not", "a", "dict"], FACT)  # type: ignore[arg-type]


def test_job_minimal_valid():
    """A pending job with only required fields validates."""
    md = {
        "id": "7c3a9f2e-1d4b-4e8a-9c5f-3e2d1a8b7c6e",
        "kind": "echo",
        "status": "pending",
        "created_at": "2026-05-22T10:14:32Z",
        "updated_at": "2026-05-22T10:14:32Z",
        "attempts": 0,
        "max_attempts": 3,
        "payload": {"message": "hi"},
    }
    validate(md, JOB)  # no raise


def test_job_with_all_optional_fields():
    """A succeeded job with every optional field validates."""
    md = {
        "id": "7c3a9f2e-1d4b-4e8a-9c5f-3e2d1a8b7c6e",
        "kind": "echo",
        "status": "succeeded",
        "created_at": "2026-05-22T10:14:32Z",
        "updated_at": "2026-05-22T10:14:33Z",
        "attempts": 1,
        "max_attempts": 3,
        "payload": {"message": "hi"},
        "result": {"echoed": "hi"},
        "error": "",
        "next_attempt_at": "2026-05-22T10:15:00Z",
        "worker_id": "worker-1",
        "claimed_at": "2026-05-22T10:14:33Z",
        "tags": ["self-test"],
    }
    validate(md, JOB)  # no raise


def test_job_missing_required_id():
    md = {
        "kind": "echo",
        "status": "pending",
        "created_at": "2026-05-22T10:14:32Z",
        "updated_at": "2026-05-22T10:14:32Z",
        "attempts": 0,
        "max_attempts": 3,
        "payload": {},
    }
    with pytest.raises(SchemaError, match="missing required key 'id'"):
        validate(md, JOB)


def test_job_payload_must_be_dict():
    md = {
        "id": "x",
        "kind": "echo",
        "status": "pending",
        "created_at": "2026-05-22T10:14:32Z",
        "updated_at": "2026-05-22T10:14:32Z",
        "attempts": 0,
        "max_attempts": 3,
        "payload": "not a dict",
    }
    with pytest.raises(SchemaError, match="payload"):
        validate(md, JOB)


def test_job_attempts_must_be_int():
    md = {
        "id": "x",
        "kind": "echo",
        "status": "pending",
        "created_at": "2026-05-22T10:14:32Z",
        "updated_at": "2026-05-22T10:14:32Z",
        "attempts": "0",  # string, not int
        "max_attempts": 3,
        "payload": {},
    }
    with pytest.raises(SchemaError, match="attempts"):
        validate(md, JOB)


def test_job_result_must_be_dict_when_present():
    md = {
        "id": "x",
        "kind": "echo",
        "status": "succeeded",
        "created_at": "2026-05-22T10:14:32Z",
        "updated_at": "2026-05-22T10:14:33Z",
        "attempts": 1,
        "max_attempts": 3,
        "payload": {},
        "result": "should be dict",
    }
    with pytest.raises(SchemaError, match="result"):
        validate(md, JOB)


def test_job_rejects_old_type_key():
    """Regression: the old JOB schema used 'type' — make sure that
    field is now rejected as unknown."""
    md = {
        "type": "job",  # old field, should now be unknown
        "id": "x",
        "kind": "echo",
        "status": "pending",
        "created_at": "2026-05-22T10:14:32Z",
        "updated_at": "2026-05-22T10:14:32Z",
        "attempts": 0,
        "max_attempts": 3,
        "payload": {},
    }
    with pytest.raises(SchemaError, match="unexpected keys"):
        validate(md, JOB)


def test_job_rejects_old_last_error_key():
    """Regression: old JOB used 'last_error' — now it's 'error'."""
    md = {
        "id": "x",
        "kind": "echo",
        "status": "failed",
        "created_at": "2026-05-22T10:14:32Z",
        "updated_at": "2026-05-22T10:14:33Z",
        "attempts": 1,
        "max_attempts": 3,
        "payload": {},
        "last_error": "something",  # old field
    }
    with pytest.raises(SchemaError, match="unexpected keys"):
        validate(md, JOB)


def test_schema_for_jobs_path_returns_job():
    """The registry still routes 'jobs/<id>.md' to the JOB schema."""
    assert schema_for("jobs/abc.md") is JOB
