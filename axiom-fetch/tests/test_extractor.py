"""
Tests for axiom_fetch.extractor.

Pure-function tests. No network, no fixtures on disk — HTML strings live
inline in the tests so the failure mode is always visible right next to
the assertion.
"""

from __future__ import annotations

import pytest
from axiom_fetch.extractor import (
    ExtractResult,
    UnsupportedContentType,
    extract,
)

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_text_html_routes_to_html_extractor(self):
        html = b"<html><body><p>hello</p></body></html>"
        result = extract(html, "text/html")
        assert isinstance(result, ExtractResult)
        assert "hello" in result.markdown

    def test_text_html_with_charset_routes_to_html(self):
        html = b"<html><body><p>hello</p></body></html>"
        result = extract(html, "text/html; charset=utf-8")
        assert "hello" in result.markdown

    def test_application_xhtml_routes_to_html(self):
        # We dispatch on "html" substring — xhtml should match.
        xhtml = b"<html><body><p>hello</p></body></html>"
        result = extract(xhtml, "application/xhtml+xml")
        assert "hello" in result.markdown

    def test_text_plain_routes_to_plain_extractor(self):
        result = extract(b"just some text", "text/plain")
        assert result.markdown == "just some text"
        assert result.title is None

    def test_text_plain_with_charset_routes_to_plain(self):
        result = extract(b"hello world", "text/plain; charset=utf-8")
        assert result.markdown == "hello world"

    def test_unknown_content_type_raises(self):
        with pytest.raises(UnsupportedContentType, match="application/octet-stream"):
            extract(b"opaque bytes", "application/octet-stream")

    def test_none_content_type_raises(self):
        with pytest.raises(UnsupportedContentType, match="None"):
            extract(b"<html></html>", None)

    def test_non_bytes_body_raises(self):
        with pytest.raises(ValueError, match="body must be bytes"):
            extract("not bytes", "text/html")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------


class TestTitleExtraction:
    def test_title_tag_wins(self):
        html = b"""
        <html>
          <head><title>Page Title</title></head>
          <body><h1>H1 Heading</h1></body>
        </html>
        """
        result = extract(html, "text/html")
        assert result.title == "Page Title"

    def test_h1_fallback_when_no_title(self):
        html = b"<html><body><h1>Just an H1</h1><p>content</p></body></html>"
        result = extract(html, "text/html")
        assert result.title == "Just an H1"

    def test_h1_fallback_when_title_is_empty(self):
        html = b"""
        <html>
          <head><title>   </title></head>
          <body><h1>The Real Title</h1></body>
        </html>
        """
        result = extract(html, "text/html")
        assert result.title == "The Real Title"

    def test_none_when_neither_present(self):
        html = b"<html><body><p>nothing here</p></body></html>"
        result = extract(html, "text/html")
        assert result.title is None

    def test_title_strips_whitespace(self):
        html = b"<html><head><title>  Spacey Title  </title></head><body></body></html>"
        result = extract(html, "text/html")
        assert result.title == "Spacey Title"


# ---------------------------------------------------------------------------
# Main content selection
# ---------------------------------------------------------------------------


class TestMainContent:
    def test_main_tag_wins_over_article(self):
        html = b"""
        <html><body>
          <article><p>article content</p></article>
          <main><p>main content</p></main>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "main content" in result.markdown
        assert "article content" not in result.markdown

    def test_article_used_when_no_main(self):
        html = b"""
        <html><body>
          <div><p>generic div content</p></div>
          <article><p>article content</p></article>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "article content" in result.markdown
        assert "generic div content" not in result.markdown

    def test_role_main_used_when_no_main_or_article(self):
        html = b"""
        <html><body>
          <div><p>random div</p></div>
          <div role="main"><p>role main content</p></div>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "role main content" in result.markdown

    def test_body_used_as_last_resort(self):
        html = b"""
        <html><body>
          <p>just body content</p>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "just body content" in result.markdown

    def test_no_body_falls_back_to_whole_document(self):
        # A bare fragment with no <body> wrapper.
        html = b"<p>fragment content</p>"
        result = extract(html, "text/html")
        assert "fragment content" in result.markdown


# ---------------------------------------------------------------------------
# Chrome stripping
# ---------------------------------------------------------------------------


class TestChromeStripping:
    def test_script_stripped(self):
        html = b"""
        <html><body>
          <script>alert('hi')</script>
          <p>real content</p>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "alert" not in result.markdown
        assert "real content" in result.markdown

    def test_style_stripped(self):
        html = b"""
        <html><body>
          <style>.x { color: red; }</style>
          <p>real content</p>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "color: red" not in result.markdown
        assert "real content" in result.markdown

    def test_nav_stripped(self):
        html = b"""
        <html><body>
          <nav><a href="/x">menu link</a></nav>
          <p>real content</p>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "menu link" not in result.markdown
        assert "real content" in result.markdown

    def test_footer_stripped(self):
        html = b"""
        <html><body>
          <p>real content</p>
          <footer>copyright notice</footer>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "copyright notice" not in result.markdown
        assert "real content" in result.markdown

    def test_header_stripped_inside_article(self):
        """Locked decision: strip <header> everywhere, including inside <article>."""
        html = b"""
        <html><body>
          <article>
            <header>byline metadata</header>
            <p>article body text</p>
          </article>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "byline metadata" not in result.markdown
        assert "article body text" in result.markdown

    def test_aside_stripped(self):
        html = b"""
        <html><body>
          <article>
            <p>main text</p>
            <aside>related links</aside>
          </article>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "related links" not in result.markdown
        assert "main text" in result.markdown

    def test_noscript_stripped(self):
        html = b"""
        <html><body>
          <noscript>please enable javascript</noscript>
          <p>real content</p>
        </body></html>
        """
        result = extract(html, "text/html")
        assert "enable javascript" not in result.markdown


# ---------------------------------------------------------------------------
# Markdown output shape
# ---------------------------------------------------------------------------


class TestMarkdownOutput:
    def test_h1_becomes_hash(self):
        html = b"<html><body><h1>Heading</h1></body></html>"
        result = extract(html, "text/html")
        assert "# Heading" in result.markdown

    def test_h2_becomes_double_hash(self):
        html = b"<html><body><h2>Subheading</h2></body></html>"
        result = extract(html, "text/html")
        assert "## Subheading" in result.markdown

    def test_paragraphs_separated_by_blank_line(self):
        html = b"<html><body><p>One.</p><p>Two.</p></body></html>"
        result = extract(html, "text/html")
        assert "One." in result.markdown
        assert "Two." in result.markdown

    def test_link_becomes_markdown_link(self):
        html = b'<html><body><p>See <a href="https://x.com">the site</a>.</p></body></html>'
        result = extract(html, "text/html")
        assert "[the site](https://x.com)" in result.markdown

    def test_runs_of_blank_lines_collapsed(self):
        # Lots of empty paragraphs should not produce huge blank gaps.
        html = b"<html><body><p>A</p><p></p><p></p><p></p><p>B</p></body></html>"
        result = extract(html, "text/html")
        # No more than one consecutive blank line anywhere.
        assert "\n\n\n" not in result.markdown

    def test_leading_and_trailing_whitespace_stripped(self):
        html = b"<html><body><p>content</p></body></html>"
        result = extract(html, "text/html")
        assert result.markdown == result.markdown.strip()


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------


class TestPlainText:
    def test_simple_plain_text(self):
        result = extract(b"just a string", "text/plain")
        assert result.markdown == "just a string"
        assert result.title is None

    def test_plain_text_whitespace_stripped(self):
        result = extract(b"\n\n  hello  \n\n", "text/plain")
        assert result.markdown == "hello"

    def test_plain_text_multiline_preserved(self):
        result = extract(b"line one\nline two\nline three", "text/plain")
        assert "line one" in result.markdown
        assert "line two" in result.markdown
        assert "line three" in result.markdown

    def test_malformed_utf8_does_not_crash(self):
        # Invalid UTF-8 byte sequence. Should decode with replacement.
        result = extract(b"valid \xff\xfe invalid", "text/plain")
        assert "valid" in result.markdown
        # Should not raise.


# ---------------------------------------------------------------------------
# Realistic-ish full document
# ---------------------------------------------------------------------------


class TestRealisticDocument:
    """One end-to-end test against a document that has all the moving parts."""

    def test_full_document_extraction(self):
        html = b"""
        <!DOCTYPE html>
        <html>
          <head>
            <title>How TCP Works</title>
            <script>analytics()</script>
            <style>body { margin: 0; }</style>
          </head>
          <body>
            <header>
              <nav>
                <a href="/">Home</a>
                <a href="/blog">Blog</a>
              </nav>
            </header>
            <main>
              <article>
                <header>By Mono, May 2026</header>
                <h1>How TCP Works</h1>
                <p>TCP is a reliable transport protocol.</p>
                <h2>The Three-Way Handshake</h2>
                <p>Client sends SYN. Server replies SYN-ACK. Client sends ACK.</p>
                <aside>See also: UDP.</aside>
              </article>
            </main>
            <footer>Copyright 2026</footer>
          </body>
        </html>
        """
        result = extract(html, "text/html")

        # Title
        assert result.title == "How TCP Works"

        # Real content present
        assert "TCP is a reliable transport protocol" in result.markdown
        assert "Three-Way Handshake" in result.markdown
        assert "SYN" in result.markdown

        # Chrome gone
        assert "analytics()" not in result.markdown
        assert "margin: 0" not in result.markdown
        assert "Home" not in result.markdown
        assert "Blog" not in result.markdown
        assert "By Mono" not in result.markdown
        assert "See also: UDP" not in result.markdown
        assert "Copyright 2026" not in result.markdown

        # Heading levels preserved
        assert "# How TCP Works" in result.markdown
        assert "## The Three-Way Handshake" in result.markdown
