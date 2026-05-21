"""
Hybrid framing protocol for axiom-store.

Wire format (request and response are structurally identical):

    <first-line>\n
    Header-Name: value\n
    Header-Name: value\n
    \n
    <exactly Content-Length bytes of body>

For requests, the first line is `<VERB> <path>` (e.g., `WRITE memory/facts/x.md`).
For responses, the first line is `<STATUS>` (e.g., `OK`, `NOT_FOUND`).

Both require a `Content-Length: N` header. `Content-Length: 0` is allowed
and means no body bytes follow the blank line.

This module is pure-function:
    - parse_request_headers(header_bytes) -> RequestStub
    - parse_response_headers(header_bytes) -> ResponseStub
    - format_request(request) -> bytes
    - format_response(response) -> bytes

The transport (sockets, recv_exact) lives in tcp_server.py / tcp_client.py.
Splitting parsing from transport keeps this module trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass


# Verbs and statuses are strings, not enums. Strings are what's on the wire;
# round-tripping through an enum is more ceremony than it's worth for a
# closed set of five values that lives in one place.
VERBS = frozenset({"READ", "WRITE", "LIST", "DELETE"})
STATUSES = frozenset({"OK", "NOT_FOUND", "SCHEMA_ERROR", "BAD_REQUEST", "SERVER_ERROR"})

HEADER_END = b"\n\n"
MAX_HEADER_BYTES = 8192  # generous; vault paths shouldn't be anywhere near this
MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB hard cap on a single message body


class ProtocolError(ValueError):
    """Raised when bytes on the wire don't conform to the framing protocol."""


@dataclass(frozen=True)
class Request:
    verb: str
    path: str
    body: bytes


@dataclass(frozen=True)
class Response:
    status: str
    body: bytes


@dataclass(frozen=True)
class RequestStub:
    """Parsed headers of a request; body is read from the socket separately."""

    verb: str
    path: str
    content_length: int


@dataclass(frozen=True)
class ResponseStub:
    """Parsed headers of a response; body is read from the socket separately."""

    status: str
    content_length: int


# ---------------------------------------------------------------------------
# Header parsing helpers (shared between request and response)
# ---------------------------------------------------------------------------


def _split_header_block(header_bytes: bytes) -> tuple[str, dict[str, str]]:
    """
    Split a header block into (first_line, headers_dict).

    Expects header_bytes to be the bytes BEFORE the blank-line terminator
    (i.e., not including the final \\n\\n). All header lines are decoded
    as UTF-8.
    """
    try:
        text = header_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ProtocolError(f"header bytes are not valid UTF-8: {e}") from e

    lines = text.split("\n")
    if not lines or not lines[0]:
        raise ProtocolError("missing first line in headers")

    first_line = lines[0]
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            # Blank line inside the block (not the terminator) is malformed.
            raise ProtocolError("unexpected blank line in header block")
        if ":" not in line:
            raise ProtocolError(f"malformed header line: {line!r}")
        name, _, value = line.partition(":")
        # Headers are case-sensitive in this protocol; require lowercase names.
        if name != name.lower():
            raise ProtocolError(f"header name must be lowercase, got {name!r}")
        if name in headers:
            raise ProtocolError(f"duplicate header: {name!r}")
        headers[name] = value.lstrip(" ")
    return first_line, headers


def _content_length(headers: dict[str, str]) -> int:
    if "content-length" not in headers:
        raise ProtocolError("missing required header: content-length")
    raw = headers["content-length"]
    try:
        n = int(raw)
    except ValueError:
        raise ProtocolError(f"content-length is not an integer: {raw!r}") from None
    if n < 0:
        raise ProtocolError(f"content-length is negative: {n}")
    if n > MAX_BODY_BYTES:
        raise ProtocolError(f"content-length {n} exceeds maximum {MAX_BODY_BYTES}")
    return n


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------


def parse_request_headers(header_bytes: bytes) -> RequestStub:
    """
    Parse the header portion of a request.

    `header_bytes` should NOT include the terminating blank line — the
    caller (server) strips it after reading up to "\\n\\n".

    Returns a RequestStub. The body is read separately from the socket
    using the returned content_length.

    Raises ProtocolError on malformed input.
    """
    first_line, headers = _split_header_block(header_bytes)

    parts = first_line.split(" ", 1)
    if len(parts) != 2:
        raise ProtocolError(f"malformed request line: {first_line!r} (want '<VERB> <path>')")
    verb, path = parts
    if verb not in VERBS:
        raise ProtocolError(f"unknown verb: {verb!r}")
    if not path:
        raise ProtocolError("empty path in request line")

    length = _content_length(headers)
    return RequestStub(verb=verb, path=path, content_length=length)


def format_request(request: Request) -> bytes:
    """Format a complete Request as bytes ready to send on the wire."""
    if request.verb not in VERBS:
        raise ProtocolError(f"unknown verb: {request.verb!r}")
    if not request.path:
        raise ProtocolError("empty path")
    if not isinstance(request.body, bytes):
        raise ProtocolError(f"body must be bytes, got {type(request.body).__name__}")

    headers = (f"{request.verb} {request.path}\ncontent-length: {len(request.body)}\n\n").encode(
        "utf-8"
    )
    return headers + request.body


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_response_headers(header_bytes: bytes) -> ResponseStub:
    """Parse the header portion of a response."""
    first_line, headers = _split_header_block(header_bytes)
    status = first_line.strip()
    if status not in STATUSES:
        raise ProtocolError(f"unknown status: {status!r}")
    length = _content_length(headers)
    return ResponseStub(status=status, content_length=length)


def format_response(response: Response) -> bytes:
    """Format a complete Response as bytes ready to send on the wire."""
    if response.status not in STATUSES:
        raise ProtocolError(f"unknown status: {response.status!r}")
    if not isinstance(response.body, bytes):
        raise ProtocolError(f"body must be bytes, got {type(response.body).__name__}")

    headers = (f"{response.status}\ncontent-length: {len(response.body)}\n\n").encode("utf-8")
    return headers + response.body
