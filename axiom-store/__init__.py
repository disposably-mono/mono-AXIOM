"""
axiom-store: persistent state layer for Mono-AXIOM.
Markdown-backed vault store with a TCP interface and write-through cache.
Implements: frontmatter parsing/rendering, filesystem layer, write-through
cache, schema validation, hybrid framing protocol, TCP server, TCP client.
"""

from axiom_store.cache import CachedVaultStore
from axiom_store.client import StoreClient, StoreError
from axiom_store.filesystem import InvalidVaultPath, VaultFS
from axiom_store.frontmatter import (
    FrontmatterError,
    parse_frontmatter,
    render_frontmatter,
)
from axiom_store.protocol import (
    ProtocolError,
    Request,
    RequestStub,
    Response,
    ResponseStub,
    format_request,
    format_response,
    parse_request_headers,
    parse_response_headers,
)
from axiom_store.schema import (
    CONVERSATION,
    FACT,
    FETCH_CHUNK,
    FETCH_SOURCE,
    JOB,
    PERSONA,
    SUMMARY,
    Schema,
    SchemaError,
    schema_for,
    validate,
)

__all__ = [
    "CONVERSATION",
    "CachedVaultStore",
    "FACT",
    "FETCH_CHUNK",
    "FETCH_SOURCE",
    "FrontmatterError",
    "InvalidVaultPath",
    "JOB",
    "PERSONA",
    "ProtocolError",
    "Request",
    "RequestStub",
    "Response",
    "ResponseStub",
    "SUMMARY",
    "Schema",
    "SchemaError",
    "StoreClient",
    "StoreError",
    "VaultFS",
    "format_request",
    "format_response",
    "parse_frontmatter",
    "parse_request_headers",
    "parse_response_headers",
    "render_frontmatter",
    "schema_for",
    "validate",
]
