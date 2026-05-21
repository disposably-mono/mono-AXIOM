"""Tests for axiom_store.frontmatter."""

import pytest

from axiom_store.frontmatter import (
    FrontmatterError,
    parse_frontmatter,
    render_frontmatter,
)


# ---------------------------------------------------------------------------
# parse_frontmatter — the seven spec cases
# ---------------------------------------------------------------------------


def test_parse_standard_frontmatter():
    text = "---\ntype: fact\ntags: [python, gil]\n---\n\nThe body.\n"
    metadata, body = parse_frontmatter(text)
    assert metadata == {"type": "fact", "tags": ["python", "gil"]}
    assert body == "The body.\n"


def test_parse_no_frontmatter():
    text = "Just a body, no frontmatter.\n"
    metadata, body = parse_frontmatter(text)
    assert metadata == {}
    assert body == "Just a body, no frontmatter.\n"


def test_parse_empty_frontmatter_block():
    text = "---\n---\n\nBody here.\n"
    metadata, body = parse_frontmatter(text)
    assert metadata == {}
    assert body == "Body here.\n"


def test_parse_frontmatter_no_body():
    text = "---\ntype: fact\n---\n"
    metadata, body = parse_frontmatter(text)
    assert metadata == {"type": "fact"}
    assert body == ""


def test_parse_malformed_unclosed_fence():
    text = "---\ntype: fact\n\nBody but no closing fence.\n"
    with pytest.raises(FrontmatterError):
        parse_frontmatter(text)


def test_parse_empty_file():
    metadata, body = parse_frontmatter("")
    assert metadata == {}
    assert body == ""


def test_parse_mid_document_fence_is_not_frontmatter():
    # A '---' in the middle of a document (e.g., a horizontal rule) must NOT
    # be treated as frontmatter. Only an opening '---' on line 1 counts.
    text = "Some intro text.\n\n---\n\nA section break.\n"
    metadata, body = parse_frontmatter(text)
    assert metadata == {}
    assert body == text


# ---------------------------------------------------------------------------
# parse_frontmatter — additional edge cases
# ---------------------------------------------------------------------------


def test_parse_frontmatter_yaml_not_a_mapping_raises():
    # YAML that parses to a list, not a dict. Must reject.
    text = "---\n- one\n- two\n---\n\nBody.\n"
    with pytest.raises(FrontmatterError):
        parse_frontmatter(text)


def test_parse_frontmatter_invalid_yaml_raises():
    text = "---\nkey: value\n  bad: indent\n---\n\nBody.\n"
    with pytest.raises(FrontmatterError):
        parse_frontmatter(text)


# ---------------------------------------------------------------------------
# render_frontmatter
# ---------------------------------------------------------------------------


def test_render_empty_metadata_returns_body_only():
    assert render_frontmatter({}, "Just the body.\n") == "Just the body.\n"


def test_render_simple_metadata():
    out = render_frontmatter({"type": "fact"}, "The body.\n")
    # Don't be too picky about exact YAML formatting — round-trip through
    # parse to check meaning.
    metadata, body = parse_frontmatter(out)
    assert metadata == {"type": "fact"}
    assert body == "The body.\n"


def test_render_rejects_non_dict_metadata():
    with pytest.raises(FrontmatterError):
        render_frontmatter(["not", "a", "dict"], "body")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Roundtrip property
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metadata,body",
    [
        ({}, ""),
        ({}, "Just a body.\n"),
        ({"type": "fact"}, ""),
        ({"type": "fact"}, "A simple body.\n"),
        ({"type": "fact", "tags": ["a", "b"]}, "Body with tags.\n"),
        ({"nested": {"key": "value"}}, "Body with nested metadata.\n"),
    ],
)
def test_roundtrip(metadata, body):
    rendered = render_frontmatter(metadata, body)
    parsed_metadata, parsed_body = parse_frontmatter(rendered)
    assert parsed_metadata == metadata
    assert parsed_body == body
