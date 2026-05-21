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
