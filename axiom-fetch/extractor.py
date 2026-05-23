"""
Content extractor for axiom-fetch.

Given raw response bytes and a content type, produce clean Markdown ready
for chunking. Dispatches by content type to specialized extractors:

  text/html      → BeautifulSoup tree, main-content heuristic, markdownify
  text/plain     → passthrough (decoded as text)
  application/pdf → pypdf page text extraction
  .docx          → python-docx paragraph/table extraction

This module is pure-function: no I/O, no network, no vault. Bytes in,
ExtractResult out.
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup
from markdownify import markdownify

# ---------------------------------------------------------------------------
# Tags that always represent chrome, never content. Stripped from any HTML
# tree before extraction, regardless of where they sit. Locked-in decision:
# strip everywhere. An in-article <header> is almost always byline metadata,
# which we don't want polluting retrieval chunks.
# ---------------------------------------------------------------------------

_CHROME_TAGS = ("script", "style", "nav", "header", "footer", "aside", "noscript")

# Main-content selector priority. First hit wins.
#   1. <main>                — HTML5 says this is the unique principal content.
#   2. <article>             — strong semantic signal.
#   3. <div role="main">     — older sites mimicking <main> via ARIA.
#   4. <body>                — universal fallback.
# If even <body> isn't present (e.g. a fragment, not a full document),
# we fall back to the whole soup.

_HTML_PARSER = "html.parser"  # stdlib parser. No lxml dependency.


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


class UnsupportedContentType(ValueError):
    """Raised when no extractor handles the given content type."""


@dataclass(frozen=True)
class ExtractResult:
    """
    The output of extraction.

      markdown: the cleaned content as Markdown text.
      title:    the page title if we could extract one, else None.

    Other metadata (source URL, content type, fetch timestamp) lives on
    the FetchResult that the caller already has — the extractor's job is
    just to add Markdown and a title.
    """

    markdown: str
    title: str | None


def extract(body: bytes, content_type: str | None) -> ExtractResult:
    """
    Dispatch to the right extractor based on content type.

    Args:
        body: Raw response bytes.
        content_type: HTTP Content-Type header value, or None.

    Returns:
        ExtractResult with markdown and optional title.

    Raises:
        UnsupportedContentType: If no extractor handles the given type.
        ValueError: If body is not bytes.
    """
    if not isinstance(body, bytes):
        raise ValueError(f"body must be bytes, got {type(body).__name__}")

    ct = (content_type or "").lower()

    if "html" in ct:
        return _extract_html(body)
    if "text/plain" in ct:
        return _extract_plain(body)
    if "application/pdf" in ct:
        from axiom_fetch.pdf_extractor import extract_pdf

        return extract_pdf(body)
    if "wordprocessingml.document" in ct:
        from axiom_fetch.docx_extractor import extract_docx

        return extract_docx(body)

    raise UnsupportedContentType(f"no extractor for content_type={content_type!r}")


# ---------------------------------------------------------------------------
# HTML extractor
# ---------------------------------------------------------------------------


def _extract_html(body: bytes) -> ExtractResult:
    """
    HTML → Markdown via BeautifulSoup + markdownify.

    Steps:
      1. Parse bytes into a tree. BeautifulSoup handles encoding detection.
      2. Extract the title (from <title>, falling back to first <h1>).
      3. Strip chrome tags everywhere (script/style/nav/header/footer/aside).
      4. Find the main content element via priority heuristic.
      5. Serialize that element's inner HTML through markdownify.
      6. Normalize whitespace (collapse runs of blank lines).
    """
    soup = BeautifulSoup(body, _HTML_PARSER)

    title = _extract_title(soup)

    # Strip chrome before we go looking for main content. This way, even if
    # a <header> sits inside <main>, it's gone before extraction.
    for tag_name in _CHROME_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    main = _find_main_content(soup)

    # markdownify accepts an HTML string. Get the inner HTML of the main
    # element. If main is the whole soup, that's the document.
    html_str = main.decode_contents() if main is not None else str(soup)

    markdown = markdownify(html_str, heading_style="ATX")
    markdown = _normalize_whitespace(markdown)

    return ExtractResult(markdown=markdown, title=title)


def _extract_title(soup: BeautifulSoup) -> str | None:
    """
    Extract title using locked priority: <title> first, then first <h1>.

    Rationale: <title> is the author's explicit declaration of what the
    page is. <h1> is a content fallback for pages with empty or generic
    titles ("Home | Acme Corp").
    """
    title_tag = soup.find("title")
    if title_tag is not None:
        text = title_tag.get_text(strip=True)
        if text:
            return text

    h1_tag = soup.find("h1")
    if h1_tag is not None:
        text = h1_tag.get_text(strip=True)
        if text:
            return text

    return None


def _find_main_content(soup: BeautifulSoup):
    """
    Walk the locked priority list. Return the first hit, or None if none
    match (caller falls back to the whole soup).
    """
    main = soup.find("main")
    if main is not None:
        return main

    article = soup.find("article")
    if article is not None:
        return article

    role_main = soup.find(attrs={"role": "main"})
    if role_main is not None:
        return role_main

    body = soup.find("body")
    if body is not None:
        return body

    return None


def _normalize_whitespace(text: str) -> str:
    """
    Collapse runs of 3+ blank lines down to exactly one blank line. Strip
    leading/trailing whitespace. Markdownify can leave heavy blank-line
    runs depending on the input HTML.
    """
    lines = text.splitlines()
    out: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip() == "":
            blank_run += 1
            if blank_run <= 1:
                out.append("")
        else:
            blank_run = 0
            out.append(line.rstrip())
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# Plain text extractor
# ---------------------------------------------------------------------------


def _extract_plain(body: bytes) -> ExtractResult:
    """
    text/plain → Markdown.

    Plain text is already valid Markdown (no special chars need escaping for
    most prose). We decode as UTF-8 with errors='replace' so a malformed
    byte doesn't crash the pipeline.

    Title is always None for plain text — there's no structural signal for
    where a title would live.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="replace")

    return ExtractResult(markdown=text.strip(), title=None)
