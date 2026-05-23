"""
DOCX extractor for axiom-fetch.

DOCX files are ZIP packages containing WordprocessingML. python-docx gives
us a structured view of paragraphs and tables; we walk the document body in
order so tables stay near the surrounding prose.
"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from zipfile import BadZipFile

from axiom_fetch.extractor import ExtractResult, _normalize_whitespace
from docx import Document
from docx.document import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


class EmptyExtractionError(ValueError):
    """Raised when a DOCX parses but produces no extractable text."""


def extract_docx(body: bytes) -> ExtractResult:
    """
    Extract Markdown-ish text from DOCX bytes.

    Raises:
        ValueError: If python-docx cannot open the package.
        EmptyExtractionError: If no paragraph or table text is extractable.
    """
    try:
        document = Document(BytesIO(body))
    except (BadZipFile, PackageNotFoundError) as exc:
        raise ValueError(f"invalid DOCX: {exc}") from exc

    title = _extract_title(document)
    markdown = _extract_body(document)

    if not markdown.strip():
        raise EmptyExtractionError("no extractable text in DOCX")

    return ExtractResult(markdown=markdown, title=title)


def _extract_title(document: DocxDocument) -> str | None:
    """Return the core-properties title if present and non-empty."""
    title = document.core_properties.title
    if title is None:
        return None

    stripped = str(title).strip()
    return stripped or None


def _extract_body(document: DocxDocument) -> str:
    """Extract paragraphs and tables in body order."""
    blocks: list[str] = []
    for block in _iter_body_blocks(document):
        if isinstance(block, Paragraph):
            markdown = _paragraph_to_markdown(block)
        else:
            markdown = _table_to_markdown(block)

        if markdown.strip():
            blocks.append(markdown)

    return _normalize_whitespace("\n\n".join(blocks))


def _iter_body_blocks(document: DocxDocument) -> Iterator[Paragraph | Table]:
    """Yield top-level paragraphs and tables in the order they appear."""
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _paragraph_to_markdown(paragraph: Paragraph) -> str:
    """Convert a paragraph to a small Markdown subset."""
    text = paragraph.text.strip()
    if not text:
        return ""

    style_name = paragraph.style.name if paragraph.style is not None else ""
    heading_level = _heading_level(style_name)
    if heading_level is not None:
        return f"{'#' * heading_level} {text}"

    if style_name.startswith("List Bullet"):
        return f"- {text}"
    if style_name.startswith("List Number"):
        return f"1. {text}"

    return text


def _heading_level(style_name: str) -> int | None:
    """Return the Markdown heading level for built-in Heading N styles."""
    prefix = "Heading "
    if not style_name.startswith(prefix):
        return None

    suffix = style_name.removeprefix(prefix)
    if not suffix.isdigit():
        return None

    level = int(suffix)
    if 1 <= level <= 6:
        return level

    return None


def _table_to_markdown(table: Table) -> str:
    """Convert a DOCX table to a GitHub-flavored Markdown table."""
    rows = [[_cell_text(cell.text) for cell in row.cells] for row in table.rows]
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return ""

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
    header = normalized_rows[0]
    separator = ["---"] * column_count
    body = normalized_rows[1:]

    markdown_rows = [
        _markdown_table_row(header),
        _markdown_table_row(separator),
    ]
    markdown_rows.extend(_markdown_table_row(row) for row in body)
    return "\n".join(markdown_rows)


def _cell_text(text: str) -> str:
    """Collapse cell-internal whitespace and escape Markdown table pipes."""
    return " ".join(text.split()).replace("|", "\\|")


def _markdown_table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"
