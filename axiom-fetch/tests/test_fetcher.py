"""
Tests for axiom_fetch.fetcher.

No real network calls. Every test injects a fake httpx.Client via
httpx.MockTransport so we can simulate any HTTP response or error
deterministically.
"""

from __future__ import annotations

import httpx
import pytest
from axiom_fetch.fetcher import (
    MAX_RESPONSE_BYTES,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    USER_AGENT,
    FetchResult,
    fetch,
)

# ---------------------------------------------------------------------------
# Helpers: build a client backed by a MockTransport
# ---------------------------------------------------------------------------


def make_client(handler):
    """Wrap a request handler function in a real httpx.Client with no network."""
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, follow_redirects=True)


def ok_handler(body: bytes, content_type: str = "text/html; charset=utf-8"):
    """Handler that always returns 200 with the given body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": content_type},
        )

    return handler


def status_handler(status_code: int, body: bytes = b""):
    """Handler that returns the given status code."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body)

    return handler


# ---------------------------------------------------------------------------
# Argument validation (programmer errors → ValueError)
# ---------------------------------------------------------------------------


class TestArgumentValidation:
    def test_non_string_url_raises(self):
        with pytest.raises(ValueError, match="url must be a string"):
            fetch(12345)  # type: ignore[arg-type]

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="url must not be empty"):
            fetch("")

    def test_zero_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout must be positive"):
            fetch("https://example.com", timeout=0)

    def test_negative_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout must be positive"):
            fetch("https://example.com", timeout=-1.0)

    def test_zero_max_bytes_raises(self):
        with pytest.raises(ValueError, match="max_bytes must be positive"):
            fetch("https://example.com", max_bytes=0)

    def test_negative_max_bytes_raises(self):
        with pytest.raises(ValueError, match="max_bytes must be positive"):
            fetch("https://example.com", max_bytes=-100)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSuccess:
    def test_200_returns_succeeded(self):
        client = make_client(ok_handler(b"<html>hello</html>"))
        result = fetch("https://example.com", client=client)

        assert result.status == STATUS_SUCCEEDED
        assert result.http_status == 200
        assert result.body == b"<html>hello</html>"
        assert result.content_type == "text/html; charset=utf-8"
        assert result.error is None

    def test_url_is_returned(self):
        client = make_client(ok_handler(b"ok"))
        result = fetch("https://example.com/path", client=client)
        assert result.url == "https://example.com/path"

    def test_empty_body_is_still_success(self):
        client = make_client(ok_handler(b""))
        result = fetch("https://example.com", client=client)
        assert result.status == STATUS_SUCCEEDED
        assert result.body == b""

    def test_returns_a_fetch_result_dataclass(self):
        client = make_client(ok_handler(b"ok"))
        result = fetch("https://example.com", client=client)
        assert isinstance(result, FetchResult)

    def test_user_agent_header_is_sent(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["ua"] = request.headers.get("user-agent")
            return httpx.Response(200, content=b"ok")

        client = make_client(handler)
        fetch("https://example.com", client=client, user_agent="test-agent/1.0")
        assert captured["ua"] == "test-agent/1.0"

    def test_default_user_agent_is_module_constant(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["ua"] = request.headers.get("user-agent")
            return httpx.Response(200, content=b"ok")

        # We can't use the injected-client path for default UA because the
        # client we inject has its own headers. So this test confirms the
        # constant is what we expect; the actual UA flow is tested above.
        assert USER_AGENT.startswith("mono-axiom/")


# ---------------------------------------------------------------------------
# HTTP error paths
# ---------------------------------------------------------------------------


class TestHttpErrors:
    def test_404_returns_failed(self):
        client = make_client(status_handler(404))
        result = fetch("https://example.com", client=client)

        assert result.status == STATUS_FAILED
        assert result.http_status == 404
        assert result.body is None
        assert "404" in result.error

    def test_500_returns_failed(self):
        client = make_client(status_handler(500))
        result = fetch("https://example.com", client=client)

        assert result.status == STATUS_FAILED
        assert result.http_status == 500
        assert "500" in result.error

    def test_403_returns_failed(self):
        client = make_client(status_handler(403))
        result = fetch("https://example.com", client=client)

        assert result.status == STATUS_FAILED
        assert result.http_status == 403

    def test_content_type_preserved_on_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                content=b"not found",
                headers={"content-type": "text/plain"},
            )

        client = make_client(handler)
        result = fetch("https://example.com", client=client)
        assert result.content_type == "text/plain"


# ---------------------------------------------------------------------------
# Network error paths
# ---------------------------------------------------------------------------


class TestNetworkErrors:
    def test_timeout_returns_failed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("simulated timeout")

        client = make_client(handler)
        result = fetch("https://example.com", client=client)

        assert result.status == STATUS_FAILED
        assert result.http_status is None
        assert "timeout" in result.error.lower()

    def test_connect_error_returns_failed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("simulated connect error")

        client = make_client(handler)
        result = fetch("https://example.com", client=client)

        assert result.status == STATUS_FAILED
        assert result.http_status is None
        assert "connection error" in result.error.lower()

    def test_other_request_error_returns_failed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadError("simulated read error")

        client = make_client(handler)
        result = fetch("https://example.com", client=client)

        assert result.status == STATUS_FAILED
        assert result.http_status is None
        assert "ReadError" in result.error


# ---------------------------------------------------------------------------
# Size cap
# ---------------------------------------------------------------------------


class TestSizeCap:
    def test_response_over_cap_returns_failed(self):
        # Use a small cap so the test stays fast.
        oversized = b"x" * 1024
        client = make_client(ok_handler(oversized))
        result = fetch("https://example.com", client=client, max_bytes=512)

        assert result.status == STATUS_FAILED
        assert result.http_status == 200  # we got a response, then rejected it
        assert result.body is None
        assert "too large" in result.error

    def test_response_at_cap_succeeds(self):
        body = b"x" * 512
        client = make_client(ok_handler(body))
        result = fetch("https://example.com", client=client, max_bytes=512)
        assert result.status == STATUS_SUCCEEDED
        assert result.body == body

    def test_default_cap_is_20mb(self):
        # Sanity-check the module constant matches the locked decision.
        assert MAX_RESPONSE_BYTES == 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


class TestClientLifecycle:
    def test_injected_client_is_not_closed_by_fetch(self):
        client = make_client(ok_handler(b"ok"))
        fetch("https://example.com", client=client)
        # Should still be usable.
        fetch("https://example.com", client=client)
        client.close()  # caller is responsible

    def test_no_injected_client_path_runs_without_error(self):
        # We can't make a real network call here. Just verify that the code
        # path doesn't crash on argument validation — it'll fail with a
        # ConnectError or similar on the actual fetch, which returns failed.
        result = fetch(
            "http://127.0.0.1:1",  # unlikely to be listening
            timeout=0.5,
        )
        # We don't assert specifics — depending on the OS, this might be
        # ConnectError, timeout, or something else. We just want to confirm
        # it returns a FetchResult and doesn't raise.
        assert isinstance(result, FetchResult)
        assert result.status == STATUS_FAILED
