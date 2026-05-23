"""
Tests for axiom_fetch.pdf_extractor.

PDF bytes are built inline so the tests stay hermetic and do not rely on
fixtures checked into the repository.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from axiom_fetch.extractor import ExtractResult, extract
from axiom_fetch.pdf_extractor import EmptyExtractionError, extract_pdf
from pypdf import PdfWriter


def make_pdf_with_text(text: str, *, title: str | None = "Sample PDF") -> bytes:
    """Build a minimal one-page PDF that pypdf can parse and extract."""
    pdf_text = _escape_pdf_string(text)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    stream = f"BT /F1 12 Tf 72 720 Td ({pdf_text}) Tj ET".encode("ascii")
    objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))

    trailer_info = ""
    if title is not None:
        objects.append(f"<< /Title ({_escape_pdf_string(title)}) >>".encode("ascii"))
        trailer_info = " /Info 6 0 R"

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_offset = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R{trailer_info} >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


def make_empty_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def make_encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _escape_pdf_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class TestPdfDispatch:
    def test_application_pdf_routes_to_pdf_extractor(self):
        result = extract(make_pdf_with_text("Hello from a PDF."), "application/pdf")

        assert isinstance(result, ExtractResult)
        assert "Hello from a PDF." in result.markdown

    def test_application_pdf_with_charset_routes_to_pdf(self):
        result = extract(
            make_pdf_with_text("PDF with content type parameters."),
            "application/pdf; charset=binary",
        )

        assert "PDF with content type parameters." in result.markdown


class TestPdfExtraction:
    def test_extracts_text(self):
        result = extract_pdf(make_pdf_with_text("The quick brown fox."))

        assert result.markdown == "The quick brown fox."

    def test_extracts_metadata_title(self):
        result = extract_pdf(make_pdf_with_text("Body text.", title="The PDF Title"))

        assert result.title == "The PDF Title"

    def test_missing_metadata_title_returns_none(self):
        result = extract_pdf(make_pdf_with_text("Body text.", title=None))

        assert result.title is None

    def test_empty_pdf_raises_clear_error(self):
        with pytest.raises(EmptyExtractionError, match="no extractable text"):
            extract_pdf(make_empty_pdf())

    def test_encrypted_pdf_raises_clear_error(self):
        with pytest.raises(ValueError, match="encrypted"):
            extract_pdf(make_encrypted_pdf())
