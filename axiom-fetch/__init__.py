"""axiom-fetch: HTTP retrieval, document extraction, and chunking for the vault."""

from axiom_fetch.chunker import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    Chunk,
    chunk_text,
)
from axiom_fetch.extractor import (
    ExtractResult,
    UnsupportedContentType,
    extract,
)
from axiom_fetch.fetcher import (
    MAX_RESPONSE_BYTES,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    USER_AGENT,
    FetchResult,
    fetch,
)
from axiom_fetch.ids import chunk_id_for, new_source_id, now_iso
from axiom_fetch.pipeline import (
    CHUNKS_DIR,
    SOURCES_DIR,
    STATUS_PENDING,
    TYPE_FETCH_CHUNK,
    TYPE_FETCH_SOURCE,
    ingest,
)

__all__ = [
    # fetcher
    "MAX_RESPONSE_BYTES",
    "STATUS_FAILED",
    "STATUS_SUCCEEDED",
    "USER_AGENT",
    "FetchResult",
    "fetch",
    # extractor
    "ExtractResult",
    "UnsupportedContentType",
    "extract",
    # chunker
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_OVERLAP",
    "Chunk",
    "chunk_text",
    # ids
    "chunk_id_for",
    "new_source_id",
    "now_iso",
    # pipeline
    "CHUNKS_DIR",
    "SOURCES_DIR",
    "STATUS_PENDING",
    "TYPE_FETCH_CHUNK",
    "TYPE_FETCH_SOURCE",
    "ingest",
]

