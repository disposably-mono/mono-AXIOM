"""
Frontmatter schema validation for axiom-store.

Each content type in the vault has a schema defining required and
optional frontmatter keys with their expected Python types. Writes
through the store are validated against the schema for the target path.

Lookup is by longest-prefix match against `vault_path`. Paths with no
matching schema are not validated (free-form areas like `system/`).

This module is pure-function: no I/O, no cache, no socket awareness.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class SchemaError(ValueError):
    """Raised when frontmatter does not conform to its schema."""


@dataclass(frozen=True)
class Schema:
    required: dict[str, type] = field(default_factory=dict)
    optional: dict[str, type] = field(default_factory=dict)
    allow_extra: bool = False


# ---------------------------------------------------------------------------
# Schemas per content type. Tighten as layers that consume them mature.
# ---------------------------------------------------------------------------

FACT = Schema(
    required={"type": str, "created": str},
    optional={"tags": list, "source": str, "confidence": str},
)

SUMMARY = Schema(
    required={"type": str, "created": str, "covers": list},
    optional={"tags": list},
)

CONVERSATION = Schema(
    required={"type": str, "created": str, "provider": str},
    optional={"tags": list, "title": str, "tokens": int},
)

PERSONA = Schema(
    required={"type": str, "name": str},
    optional={"tags": list, "model_hint": str},
)

JOB = Schema(
    required={
        "id": str,
        "kind": str,
        "status": str,
        "created_at": str,
        "updated_at": str,
        "attempts": int,
        "max_attempts": int,
        "payload": dict,
    },
    optional={
        "result": dict,
        "error": str,
        "next_attempt_at": str,
        "worker_id": str,
        "claimed_at": str,
        "tags": list,
    },
)

FETCH_SOURCE = Schema(
    required={"type": str, "url": str, "fetched_at": str},
    optional={"content_type": str, "tags": list, "title": str},
)

FETCH_CHUNK = Schema(
    required={"type": str, "source": str, "chunk_index": int},
    optional={"tags": list, "embedding_path": str},
)


# Longest prefix wins. Keep entries here; order doesn't matter — lookup
# sorts by prefix length.
_REGISTRY: dict[str, Schema] = {
    "memory/facts/": FACT,
    "memory/summaries/": SUMMARY,
    "memory/conversations/": CONVERSATION,
    "personas/": PERSONA,
    "jobs/": JOB,
    "fetch/sources/": FETCH_SOURCE,
    "fetch/chunks/": FETCH_CHUNK,
    # `fetch/uploads/`, `system/`, `exports/` intentionally absent —
    # free-form, no schema applies.
}


def schema_for(vault_path: str) -> Schema | None:
    """
    Return the schema that applies to a given vault path, or None if no
    schema applies. Uses longest-prefix matching.
    """
    best: tuple[int, Schema] | None = None
    for prefix, schema in _REGISTRY.items():
        if vault_path.startswith(prefix):
            if best is None or len(prefix) > best[0]:
                best = (len(prefix), schema)
    return best[1] if best is not None else None


def validate(metadata: dict, schema: Schema) -> None:
    """
    Validate a metadata dict against a schema.

    Raises SchemaError on the first violation found:
      - missing required key
      - wrong type for a required or optional key
      - extra (unknown) key if allow_extra is False

    Returns None on success.
    """
    if not isinstance(metadata, dict):
        raise SchemaError(f"metadata must be a dict, got {type(metadata).__name__}")

    # Required keys present?
    for key, expected_type in schema.required.items():
        if key not in metadata:
            raise SchemaError(f"missing required key {key!r}")
        if not isinstance(metadata[key], expected_type):
            raise SchemaError(
                f"key {key!r} must be {expected_type.__name__}, got {type(metadata[key]).__name__}"
            )

    # Optional keys, if present, have the right type?
    for key, expected_type in schema.optional.items():
        if key in metadata and not isinstance(metadata[key], expected_type):
            raise SchemaError(
                f"key {key!r} must be {expected_type.__name__}, got {type(metadata[key]).__name__}"
            )

    # Extra keys allowed?
    if not schema.allow_extra:
        known = set(schema.required) | set(schema.optional)
        extras = set(metadata) - known
        if extras:
            extras_sorted = ", ".join(sorted(repr(k) for k in extras))
            raise SchemaError(f"unexpected keys: {extras_sorted}")
