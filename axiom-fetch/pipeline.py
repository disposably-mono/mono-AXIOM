"""
Ingestion pipeline for axiom-fetch.

Wires together fetcher, extractor, and chunker, and persists the result
into the vault via an injected StoreClient (or any compatible store).

Single public function: ingest(url, store). Returns the source_id so
callers can read fetch/sources/<source_id>.md to see the outcome.

The pipeline uses a two-phase write:
  1. Write FETCH_SOURCE with status="pending" before doing any work.
     This marks intent in the vault. If we crash between phases, an
     observer can see "this attempt was interrupted".
  2. Do the work (fetch → extract → chunk).
  3. Write chunks (if any).
  4. Update FETCH_SOURCE to status="succeeded" (or "failed") with the
     terminal metadata.

The pipeline never raises on fetch/extract failures — every failure is
recorded in the source's status and error fields. ValueError is reserved
for programmer errors at the public boundary (bad URL, bad chunk parameters).

The pipeline never retries. Retries belong to axiom-queue; wrap ingest
in a job to get retry semantics.
"""

from __future__ import annotations

from axiom_fetch.chunker import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    Chunk,
    chunk_text,
)
from axiom_fetch.extractor import extract
from axiom_fetch.fetcher import STATUS_FAILED, STATUS_SUCCEEDED, fetch
from axiom_fetch.ids import chunk_id_for, new_source_id, now_iso
from axiom_store.frontmatter import render_frontmatter
from pypdf.errors import PdfReadError

# Vault paths. Trailing slash matters — these are directory prefixes.
SOURCES_DIR = "fetch/sources/"
CHUNKS_DIR = "fetch/chunks/"

# Discriminators used in `type:` frontmatter.
TYPE_FETCH_SOURCE = "fetch_source"
TYPE_FETCH_CHUNK = "fetch_chunk"

# Status vocabulary mirrors fetcher.STATUS_* but adds "pending" for the
# pre-work source write.
STATUS_PENDING = "pending"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ingest(
    url: str,
    store,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> str:
    """
    Fetch a URL, extract content, chunk it, write to the vault.

    Args:
        url: The URL to ingest. Must be a non-empty string.
        store: Anything implementing the store interface — write(path, bytes),
            read(path) -> bytes, etc. Both CachedVaultStore and StoreClient
            work here (substitutable per Phase 1's wrapper pattern).
        chunk_size: Characters per chunk. Defaults to chunker's default.
        overlap: Characters of overlap between chunks. Defaults to chunker's default.

    Returns:
        The source_id. Read fetch/sources/<source_id>.md to see the outcome.

    Raises:
        ValueError: On programmer error — bad URL, bad chunk parameters.
    """
    if not isinstance(url, str) or not url:
        raise ValueError("url must be a non-empty string")

    source_id = new_source_id()

    # Phase 1: write pending source
    _write_source(
        store=store,
        source_id=source_id,
        url=url,
        status=STATUS_PENDING,
    )

    # Phase 2: fetch
    fetch_result = fetch(url)
    if fetch_result.status == STATUS_FAILED:
        _write_source(
            store=store,
            source_id=source_id,
            url=fetch_result.url,  # may differ from original after redirects
            status=STATUS_FAILED,
            content_type=fetch_result.content_type,
            error=fetch_result.error,
        )
        return source_id

    # Phase 3: extract
    try:
        extract_result = extract(fetch_result.body, fetch_result.content_type)
    except (ValueError, PdfReadError) as exc:
        _write_source(
            store=store,
            source_id=source_id,
            url=fetch_result.url,
            status=STATUS_FAILED,
            content_type=fetch_result.content_type,
            error=str(exc),
        )
        return source_id

    # Phase 4: chunk
    chunks = chunk_text(
        extract_result.markdown,
        chunk_size=chunk_size,
        overlap=overlap,
    )

    # Phase 5: write all chunks
    for chunk in chunks:
        _write_chunk(
            store=store,
            source_id=source_id,
            chunk=chunk,
            chunk_total=len(chunks),
        )

    # Phase 6: finalize source as succeeded
    _write_source(
        store=store,
        source_id=source_id,
        url=fetch_result.url,
        status=STATUS_SUCCEEDED,
        content_type=fetch_result.content_type,
        title=extract_result.title,
        chunk_count=len(chunks),
        fetched_at=now_iso(),
    )

    return source_id


# ---------------------------------------------------------------------------
# Vault writers
# ---------------------------------------------------------------------------


def _write_source(
    *,
    store,
    source_id: str,
    url: str,
    status: str,
    content_type: str | None = None,
    title: str | None = None,
    chunk_count: int | None = None,
    fetched_at: str | None = None,
    error: str | None = None,
) -> None:
    """
    Write or overwrite a FETCH_SOURCE file in the vault.

    The frontmatter is built dynamically — optional fields are only
    included if they have a value. This keeps pending and failed sources
    minimal while letting succeeded sources carry the full metadata.
    """
    now = now_iso()
    metadata: dict = {
        "id": source_id,
        "type": TYPE_FETCH_SOURCE,
        "status": status,
        "url": url,
        "created_at": now,  # see note below — overwritten on re-write
        "updated_at": now,
    }
    if fetched_at is not None:
        metadata["fetched_at"] = fetched_at
    if content_type is not None:
        metadata["content_type"] = content_type
    if title is not None:
        metadata["title"] = title
    if error is not None:
        metadata["error"] = error
    if chunk_count is not None:
        metadata["chunk_count"] = chunk_count

    # Body is intentionally empty for sources — content lives in chunks.
    body = ""
    rendered = render_frontmatter(metadata, body)

    path = f"{SOURCES_DIR}{source_id}.md"
    store.write(path, rendered.encode("utf-8"))


def _write_chunk(
    *,
    store,
    source_id: str,
    chunk: Chunk,
    chunk_total: int,
) -> None:
    """Write a single FETCH_CHUNK file to the vault."""
    chunk_id = chunk_id_for(source_id, chunk.index)
    metadata = {
        "id": chunk_id,
        "type": TYPE_FETCH_CHUNK,
        "source_id": source_id,
        "chunk_index": chunk.index,
        "chunk_total": chunk_total,
        "created_at": now_iso(),
        "char_count": chunk.char_count,
    }
    if chunk.overlap_chars > 0:
        metadata["overlap_chars"] = chunk.overlap_chars

    rendered = render_frontmatter(metadata, chunk.text)
    path = f"{CHUNKS_DIR}{chunk_id}.md"
    store.write(path, rendered.encode("utf-8"))
