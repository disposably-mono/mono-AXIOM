"""
PDF extractor for axiom-fetch.

PDF extraction is page-oriented: pypdf reconstructs text from each page's
drawing instructions, and we join page text with blank lines so page
boundaries survive chunking.
"""

from __future__ import annotations

from io import BytesIO

from axiom_fetch.extractor import ExtractResult, _normalize_whitespace
from pypdf import PdfReader


class EmptyExtractionError(ValueError):
    """Raised when a PDF parses but produces no extractable text."""


def extract_pdf(body: bytes) -> ExtractResult:
    """
    Extract Markdown-ish text from PDF bytes.

    Raises:
        ValueError: If the PDF is encrypted.
        EmptyExtractionError: If no page produces extractable text.
        pypdf.errors.PdfReadError: If pypdf cannot parse the PDF.
    """
    reader = PdfReader(BytesIO(body))

    if reader.is_encrypted:
        raise ValueError("PDF is encrypted; cannot extract")

    title = _extract_title(reader)
    markdown = _extract_all_pages(reader)

    if not markdown.strip():
        raise EmptyExtractionError("no extractable text in PDF")

    return ExtractResult(markdown=markdown, title=title)


def _extract_title(reader: PdfReader) -> str | None:
    """Return the metadata title if present and non-empty."""
    metadata = reader.metadata
    if metadata is None:
        return None

    title = metadata.title
    if title is None:
        return None

    stripped = str(title).strip()
    return stripped or None


def _extract_all_pages(reader: PdfReader) -> str:
    """Extract text from all pages and normalize the joined result."""
    page_texts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            page_texts.append(text)

    return _normalize_whitespace("\n\n".join(page_texts))
