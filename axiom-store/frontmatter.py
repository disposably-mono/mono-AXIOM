"""
Frontmatter parsing and rendering for Markdown documents.

A document is a Markdown file with optional YAML frontmatter delimited by
'---' lines at the start of the file:

    ---
    type: fact
    tags: [python, gil]
    ---

    The body of the document goes here.

This module provides:
    parse_frontmatter(text) -> (metadata, body)
    render_frontmatter(metadata, body) -> text

Both operate on strings. Filesystem I/O is handled elsewhere.
"""

from __future__ import annotations

import yaml


class FrontmatterError(ValueError):
    """Raised when a document's frontmatter block is malformed."""


_FENCE = "---"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    Split a Markdown document into (metadata, body).

    Rules:
        - If the document does not start with a '---' line, there is no
          frontmatter. Returns ({}, text).
        - If it does start with '---', the frontmatter block runs until the
          next '---' line. The block is parsed as YAML.
        - An empty frontmatter block ('---\\n---\\n') yields {}.
        - If the opening '---' has no matching closing '---', raises
          FrontmatterError.
        - The body is everything after the closing '---', with a single
          leading newline stripped if present.

    Returns:
        (metadata, body) where metadata is always a dict (possibly empty)
        and body is always a string (possibly empty).

    Raises:
        FrontmatterError: if the frontmatter block is malformed (unclosed
            fence, or YAML that doesn't parse to a mapping).
    """
    # Empty file: no frontmatter, empty body.
    if not text:
        return {}, ""

    lines = text.split("\n")

    # No opening fence -> no frontmatter, body is the whole text.
    if lines[0] != _FENCE:
        return {}, text

    # Look for the closing fence, starting from line 1.
    closing_index = None
    for i in range(1, len(lines)):
        if lines[i] == _FENCE:
            closing_index = i
            break

    if closing_index is None:
        raise FrontmatterError(
            "Frontmatter block is not closed: opening '---' has no matching '---'"
        )

    # Frontmatter content is everything between the fences (exclusive).
    fm_text = "\n".join(lines[1:closing_index])

    # Empty frontmatter block -> empty metadata.
    if fm_text.strip() == "":
        metadata: dict = {}
    else:
        try:
            parsed = yaml.safe_load(fm_text)
        except yaml.YAMLError as e:
            raise FrontmatterError(f"Frontmatter is not valid YAML: {e}") from e
        if parsed is None:
            metadata = {}
        elif isinstance(parsed, dict):
            metadata = parsed
        else:
            raise FrontmatterError(
                f"Frontmatter must be a YAML mapping, got {type(parsed).__name__}"
            )

    # Body is everything after the closing fence.
    body_lines = lines[closing_index + 1 :]
    body = "\n".join(body_lines)

    # Strip a single leading newline if the body starts with one. This is the
    # common case: '---\n<body>' where the author put a blank line after the
    # closing fence for readability. We want the body to start at the first
    # real content line, not with an artifact of the fence formatting.
    if body.startswith("\n"):
        body = body[1:]

    return metadata, body


def render_frontmatter(metadata: dict, body: str) -> str:
    """
    Assemble a Markdown document from metadata and body.

    Inverse of parse_frontmatter for the common case:
        parse_frontmatter(render_frontmatter(m, b)) == (m, b)
    (for all m that are YAML-roundtrippable mappings and all b)

    Rules:
        - If metadata is empty, no frontmatter block is emitted. Returns just
          the body. (This matches the no-frontmatter case in parse_frontmatter.)
        - If metadata is non-empty, emits:
              ---\\n<yaml>---\\n\\n<body>
          The blank line between the closing fence and the body is the
          standard convention and is stripped back off on parse.
        - The body is emitted verbatim. Caller is responsible for trailing
          newlines if they want them.

    Args:
        metadata: dict to serialize as YAML. Must be YAML-serializable.
        body: the document body as a string.

    Returns:
        The complete document text.

    Raises:
        FrontmatterError: if metadata is not a dict, or if it fails to
            serialize as YAML.
    """
    if not isinstance(metadata, dict):
        raise FrontmatterError(f"metadata must be a dict, got {type(metadata).__name__}")

    if not metadata:
        return body

    try:
        yaml_text = yaml.safe_dump(
            metadata,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
    except yaml.YAMLError as e:
        raise FrontmatterError(f"metadata failed to serialize as YAML: {e}") from e

    # safe_dump always ends with '\n', so yaml_text already ends cleanly.
    return f"{_FENCE}\n{yaml_text}{_FENCE}\n\n{body}"
