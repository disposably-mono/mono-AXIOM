"""Tests for axiom_store.protocol."""

import pytest

from axiom_store.protocol import (
    MAX_BODY_BYTES,
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


# ---------------------------------------------------------------------------
# parse_request_headers
# ---------------------------------------------------------------------------


def test_parse_request_minimal():
    headers = b"READ memory/facts/x.md\ncontent-length: 0"
    stub = parse_request_headers(headers)
    assert stub == RequestStub(verb="READ", path="memory/facts/x.md", content_length=0)


def test_parse_request_with_body_length():
    headers = b"WRITE x.md\ncontent-length: 42"
    stub = parse_request_headers(headers)
    assert stub.verb == "WRITE"
    assert stub.path == "x.md"
    assert stub.content_length == 42


def test_parse_request_unknown_verb_raises():
    with pytest.raises(ProtocolError, match="unknown verb"):
        parse_request_headers(b"FROBNICATE x.md\ncontent-length: 0")


def test_parse_request_missing_path_raises():
    with pytest.raises(ProtocolError, match="malformed request line"):
        parse_request_headers(b"READ\ncontent-length: 0")


def test_parse_request_empty_path_raises():
    # "READ " has the space but nothing after — split(" ", 1) yields ["READ", ""]
    with pytest.raises(ProtocolError, match="empty path"):
        parse_request_headers(b"READ \ncontent-length: 0")


def test_parse_request_missing_content_length_raises():
    with pytest.raises(ProtocolError, match="content-length"):
        parse_request_headers(b"READ x.md")


def test_parse_request_negative_content_length_raises():
    with pytest.raises(ProtocolError, match="negative"):
        parse_request_headers(b"READ x.md\ncontent-length: -5")


def test_parse_request_oversize_content_length_raises():
    huge = MAX_BODY_BYTES + 1
    with pytest.raises(ProtocolError, match="exceeds maximum"):
        parse_request_headers(f"READ x.md\ncontent-length: {huge}".encode())


def test_parse_request_non_integer_content_length_raises():
    with pytest.raises(ProtocolError, match="not an integer"):
        parse_request_headers(b"READ x.md\ncontent-length: lots")


def test_parse_request_uppercase_header_name_raises():
    with pytest.raises(ProtocolError, match="lowercase"):
        parse_request_headers(b"READ x.md\nContent-Length: 0")


def test_parse_request_duplicate_header_raises():
    with pytest.raises(ProtocolError, match="duplicate"):
        parse_request_headers(b"READ x.md\ncontent-length: 0\ncontent-length: 5")


def test_parse_request_invalid_utf8_raises():
    with pytest.raises(ProtocolError, match="UTF-8"):
        parse_request_headers(b"READ \xff\xfe\ncontent-length: 0")


# ---------------------------------------------------------------------------
# format_request and round-trip
# ---------------------------------------------------------------------------


def test_format_request_minimal():
    out = format_request(Request(verb="READ", path="x.md", body=b""))
    assert out == b"READ x.md\ncontent-length: 0\n\n"


def test_format_request_with_body():
    body = b"---\ntype: fact\n---\n\nhi"
    out = format_request(Request(verb="WRITE", path="memory/facts/x.md", body=body))
    assert (
        out
        == b"WRITE memory/facts/x.md\ncontent-length: " + str(len(body)).encode() + b"\n\n" + body
    )


def test_format_request_rejects_unknown_verb():
    with pytest.raises(ProtocolError):
        format_request(Request(verb="FROB", path="x.md", body=b""))


def test_request_roundtrip():
    original = Request(verb="WRITE", path="memory/facts/x.md", body=b"---\ntype: fact\n---\n\nhi")
    wire = format_request(original)

    # Simulate the server: split at the first blank line.
    header_part, _, body_part = wire.partition(b"\n\n")
    stub = parse_request_headers(header_part)
    assert stub.verb == original.verb
    assert stub.path == original.path
    assert stub.content_length == len(original.body)
    assert body_part == original.body


# ---------------------------------------------------------------------------
# parse_response_headers
# ---------------------------------------------------------------------------


def test_parse_response_ok():
    stub = parse_response_headers(b"OK\ncontent-length: 5")
    assert stub == ResponseStub(status="OK", content_length=5)


def test_parse_response_unknown_status_raises():
    with pytest.raises(ProtocolError, match="unknown status"):
        parse_response_headers(b"WAT\ncontent-length: 0")


# ---------------------------------------------------------------------------
# format_response and round-trip
# ---------------------------------------------------------------------------


def test_format_response_ok_empty():
    assert format_response(Response(status="OK", body=b"")) == b"OK\ncontent-length: 0\n\n"


def test_format_response_with_body():
    body = b"---\ntype: fact\n---\n\nhi"
    out = format_response(Response(status="OK", body=body))
    assert out == b"OK\ncontent-length: " + str(len(body)).encode() + b"\n\n" + body


def test_format_response_rejects_unknown_status():
    with pytest.raises(ProtocolError):
        format_response(Response(status="MAYBE", body=b""))


def test_response_roundtrip():
    original = Response(status="OK", body=b"some payload")
    wire = format_response(original)
    header_part, _, body_part = wire.partition(b"\n\n")
    stub = parse_response_headers(header_part)
    assert stub.status == original.status
    assert stub.content_length == len(original.body)
    assert body_part == original.body
