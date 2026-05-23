"""
Tests for axiom_fetch.pipeline.

We inject a fake in-memory store and monkeypatch the fetcher to return
canned FetchResults. No real network calls. The pipeline's job is to
orchestrate, not to fetch — so the tests verify what got written to the
vault and in what order, not the network behavior.
"""

from __future__ import annotations

import pytest
from axiom_fetch import pipeline as pipeline_module
from axiom_fetch.fetcher import STATUS_FAILED, STATUS_SUCCEEDED, FetchResult
from axiom_fetch.pipeline import (
    CHUNKS_DIR,
    SOURCES_DIR,
    STATUS_PENDING,
    TYPE_FETCH_CHUNK,
    TYPE_FETCH_SOURCE,
    ingest,
)
from axiom_store.frontmatter import parse_frontmatter

# ---------------------------------------------------------------------------
# Fake store — minimal substitute for StoreClient / CachedVaultStore
# ---------------------------------------------------------------------------


class FakeStore:
    """
    In-memory store that records every write in the order it happened.
    Implements just enough of the store interface to satisfy the pipeline:
    only write() is exercised.
    """

    def __init__(self):
        self.writes: list[tuple[str, bytes]] = []  # (path, body) in order
        self.data: dict[str, bytes] = {}  # final state per path

    def write(self, path: str, body: bytes) -> None:
        self.writes.append((path, body))
        self.data[path] = body

    def read(self, path: str) -> bytes:
        return self.data[path]

    def writes_for(self, path: str) -> list[bytes]:
        """Return every body written to `path`, in order."""
        return [b for (p, b) in self.writes if p == path]


def parse_source_at(store: FakeStore, source_id: str) -> dict:
    """Read and parse the FETCH_SOURCE frontmatter from the store."""
    path = f"{SOURCES_DIR}{source_id}.md"
    raw = store.read(path).decode("utf-8")
    metadata, _ = parse_frontmatter(raw)
    return metadata


def parse_chunk_at(store: FakeStore, source_id: str, index: int) -> tuple[dict, str]:
    """Read and parse a FETCH_CHUNK from the store. Returns (frontmatter, body)."""
    chunk_id = f"{source_id}-{index:04d}"
    path = f"{CHUNKS_DIR}{chunk_id}.md"
    raw = store.read(path).decode("utf-8")
    return parse_frontmatter(raw)


# ---------------------------------------------------------------------------
# Fixtures: monkeypatch the fetcher so tests are deterministic
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_fetch(monkeypatch):
    """Returns a function that installs a canned FetchResult for fetch()."""

    def _install(result: FetchResult):
        def fake_fetch(url: str, **kwargs) -> FetchResult:
            # Echo the URL into the result if not already set.
            if not result.url:
                return FetchResult(
                    url=url,
                    status=result.status,
                    http_status=result.http_status,
                    content_type=result.content_type,
                    body=result.body,
                    error=result.error,
                )
            return result

        monkeypatch.setattr(pipeline_module, "fetch", fake_fetch)

    return _install


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


class TestArgumentValidation:
    def test_empty_url_raises(self):
        store = FakeStore()
        with pytest.raises(ValueError, match="non-empty string"):
            ingest("", store)

    def test_non_string_url_raises(self):
        store = FakeStore()
        with pytest.raises(ValueError, match="non-empty string"):
            ingest(None, store)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSuccessfulIngest:
    def test_returns_a_source_id(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com/article",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/html",
                body=b"<html><head><title>T</title></head><body><p>Hello world.</p></body></html>",
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com/article", store)

        assert isinstance(source_id, str)
        assert source_id.startswith("src-")

    def test_source_file_is_written(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com/article",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/html",
                body=b"<html><body><p>Hello.</p></body></html>",
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com/article", store)

        meta = parse_source_at(store, source_id)
        assert meta["id"] == source_id
        assert meta["type"] == TYPE_FETCH_SOURCE
        assert meta["status"] == STATUS_SUCCEEDED
        assert meta["url"] == "https://example.com/article"
        assert meta["content_type"] == "text/html"
        assert "fetched_at" in meta
        assert "chunk_count" in meta

    def test_two_phase_write_pending_then_succeeded(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/html",
                body=b"<html><body><p>Hello.</p></body></html>",
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com", store)

        source_path = f"{SOURCES_DIR}{source_id}.md"
        writes = store.writes_for(source_path)
        # Expect exactly two writes: pending, then succeeded.
        assert len(writes) == 2

        first_meta, _ = parse_frontmatter(writes[0].decode("utf-8"))
        last_meta, _ = parse_frontmatter(writes[1].decode("utf-8"))

        assert first_meta["status"] == STATUS_PENDING
        assert last_meta["status"] == STATUS_SUCCEEDED

    def test_chunks_are_written(self, patch_fetch):
        # Big enough body to produce multiple chunks.
        body = b"<html><body>" + (b"<p>" + b"word " * 200 + b"</p>") * 5 + b"</body></html>"
        patch_fetch(
            FetchResult(
                url="https://example.com",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/html",
                body=body,
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com", store, chunk_size=500, overlap=50)

        meta = parse_source_at(store, source_id)
        chunk_count = meta["chunk_count"]
        assert chunk_count > 1

        # Every chunk should be readable from the store.
        for i in range(chunk_count):
            chunk_meta, chunk_body = parse_chunk_at(store, source_id, i)
            assert chunk_meta["type"] == TYPE_FETCH_CHUNK
            assert chunk_meta["source_id"] == source_id
            assert chunk_meta["chunk_index"] == i
            assert chunk_meta["chunk_total"] == chunk_count
            assert chunk_meta["char_count"] == len(chunk_body)

    def test_first_chunk_has_no_overlap_field(self, patch_fetch):
        # overlap_chars is omitted when it's zero (first chunk).
        body = b"<html><body>" + (b"<p>" + b"word " * 200 + b"</p>") * 5 + b"</body></html>"
        patch_fetch(
            FetchResult(
                url="https://example.com",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/html",
                body=body,
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com", store, chunk_size=500, overlap=50)

        chunk0_meta, _ = parse_chunk_at(store, source_id, 0)
        assert "overlap_chars" not in chunk0_meta

    def test_subsequent_chunks_have_overlap_field(self, patch_fetch):
        body = b"<html><body>" + (b"<p>" + b"word " * 200 + b"</p>") * 5 + b"</body></html>"
        patch_fetch(
            FetchResult(
                url="https://example.com",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/html",
                body=body,
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com", store, chunk_size=500, overlap=50)

        chunk1_meta, _ = parse_chunk_at(store, source_id, 1)
        assert chunk1_meta["overlap_chars"] == 50

    def test_title_extracted_from_html(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/html",
                body=b"<html><head><title>The Article</title></head><body><p>X</p></body></html>",
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com", store)

        meta = parse_source_at(store, source_id)
        assert meta["title"] == "The Article"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestFetchFailure:
    def test_fetch_failure_writes_failed_source(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com/404",
                status=STATUS_FAILED,
                http_status=404,
                content_type="text/html",
                body=None,
                error="HTTP 404",
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com/404", store)

        meta = parse_source_at(store, source_id)
        assert meta["status"] == STATUS_FAILED
        assert meta["error"] == "HTTP 404"

    def test_fetch_failure_writes_no_chunks(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com/404",
                status=STATUS_FAILED,
                http_status=404,
                content_type=None,
                body=None,
                error="HTTP 404",
            )
        )
        store = FakeStore()
        ingest("https://example.com/404", store)

        # No writes should have happened to the chunks directory.
        chunk_writes = [p for (p, _) in store.writes if p.startswith(CHUNKS_DIR)]
        assert chunk_writes == []

    def test_fetch_failure_does_not_include_chunk_count(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com/404",
                status=STATUS_FAILED,
                http_status=404,
                content_type=None,
                body=None,
                error="HTTP 404",
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com/404", store)

        meta = parse_source_at(store, source_id)
        assert "chunk_count" not in meta

    def test_fetch_failure_still_returns_source_id(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com",
                status=STATUS_FAILED,
                http_status=500,
                content_type=None,
                body=None,
                error="HTTP 500",
            )
        )
        store = FakeStore()
        result = ingest("https://example.com", store)
        assert isinstance(result, str)
        assert result.startswith("src-")


class TestExtractFailure:
    def test_unsupported_content_type_writes_failed_source(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com/file.pdf",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="application/pdf",
                body=b"%PDF-1.4 fake pdf body",
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com/file.pdf", store)

        meta = parse_source_at(store, source_id)
        assert meta["status"] == STATUS_FAILED
        assert "application/pdf" in meta["error"]

    def test_unsupported_content_type_writes_no_chunks(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com/file.pdf",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="application/pdf",
                body=b"%PDF-1.4",
                error=None,
            )
        )
        store = FakeStore()
        ingest("https://example.com/file.pdf", store)

        chunk_writes = [p for (p, _) in store.writes if p.startswith(CHUNKS_DIR)]
        assert chunk_writes == []


# ---------------------------------------------------------------------------
# Plain-text content
# ---------------------------------------------------------------------------


class TestPlainTextIngest:
    def test_plain_text_succeeds(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com/notes.txt",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/plain",
                body=b"some plain text content here",
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com/notes.txt", store)

        meta = parse_source_at(store, source_id)
        assert meta["status"] == STATUS_SUCCEEDED
        # Plain text has no title.
        assert "title" not in meta

    def test_plain_text_produces_at_least_one_chunk(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com/notes.txt",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/plain",
                body=b"some plain text content here",
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com/notes.txt", store)

        meta = parse_source_at(store, source_id)
        assert meta["chunk_count"] >= 1


# ---------------------------------------------------------------------------
# Vault paths
# ---------------------------------------------------------------------------


class TestVaultPaths:
    def test_source_written_to_sources_dir(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/html",
                body=b"<html><body><p>x</p></body></html>",
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com", store)

        expected_path = f"{SOURCES_DIR}{source_id}.md"
        assert expected_path in store.data

    def test_chunks_written_to_chunks_dir(self, patch_fetch):
        patch_fetch(
            FetchResult(
                url="https://example.com",
                status=STATUS_SUCCEEDED,
                http_status=200,
                content_type="text/html",
                body=b"<html><body><p>hello world</p></body></html>",
                error=None,
            )
        )
        store = FakeStore()
        source_id = ingest("https://example.com", store)

        # Should be at least one chunk.
        chunk_writes = [p for (p, _) in store.writes if p.startswith(CHUNKS_DIR)]
        assert len(chunk_writes) >= 1
        # Every chunk path includes the source_id.
        for path in chunk_writes:
            assert source_id in path
