"""
HTTP fetcher for axiom-fetch.

Given a URL, perform an HTTP GET and return a FetchResult capturing the
outcome. Never raises on network/HTTP failure — those become
FetchResult(status="failed", error=...). Raises ValueError only on
programmer error (bad arg types, empty URL).

The fetcher deliberately does not:
  - write to the vault (caller's job)
  - parse HTML (extractor's job)
  - retry (queue's job)
  - chunk (chunker's job)

This module is the single network boundary for the layer. Everything
downstream operates on FetchResult, not on raw httpx responses.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

USER_AGENT = "mono-axiom/0.0.1 (+https://github.com/disposably-mono/mono-AXIOM)"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 20 * 1024 * 1024  # 20 MB. Larger than axiom-store's 10 MB
# body cap because HTML pages can run big
# and the chunker will slice them down.

# Outcome vocabulary. Matches FETCH_SOURCE.status in axiom-store/schema.py.
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    """
    Captures the outcome of a single fetch.

    On success: status == STATUS_SUCCEEDED, http_status in 200-299,
    body is bytes, error is None.

    On failure: status == STATUS_FAILED, error is a human-readable string,
    body is None. http_status is set if we got an HTTP response (4xx, 5xx);
    None if the failure happened before a response (timeout, DNS, etc.).
    """

    url: str
    status: str
    http_status: int | None
    content_type: str | None
    body: bytes | None
    error: str | None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_RESPONSE_BYTES,
    user_agent: str = USER_AGENT,
    client: httpx.Client | None = None,
) -> FetchResult:
    """
    Fetch a URL over HTTP. Returns a FetchResult.

    Args:
        url: The URL to fetch. Must be a non-empty string.
        timeout: Request timeout in seconds. Must be positive.
        max_bytes: Maximum response body size in bytes. Must be positive.
        user_agent: User-Agent header to send.
        client: An httpx.Client to use. If None, a new one is created for
            this call and closed afterwards. Tests inject a fake client here.

    Returns:
        FetchResult. Never raises on network failure.

    Raises:
        ValueError: On programmer error — non-string URL, empty URL,
            non-positive timeout, non-positive max_bytes.
    """
    # ---- Argument validation (programmer errors → exceptions) ----
    if not isinstance(url, str):
        raise ValueError(f"url must be a string, got {type(url).__name__}")
    if not url:
        raise ValueError("url must not be empty")
    if timeout <= 0:
        raise ValueError(f"timeout must be positive, got {timeout}")
    if max_bytes <= 0:
        raise ValueError(f"max_bytes must be positive, got {max_bytes}")

    headers = {"User-Agent": user_agent}

    # ---- Client lifecycle ----
    # If the caller passed a client, we use it and don't close it.
    # If not, we make a one-shot client for this call.
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=timeout, follow_redirects=True)

    try:
        return _fetch_with_client(client, url, max_bytes, headers)
    finally:
        if owns_client:
            client.close()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _fetch_with_client(
    client: httpx.Client,
    url: str,
    max_bytes: int,
    headers: dict[str, str],
) -> FetchResult:
    """
    The real fetch logic, split out so the client lifecycle in fetch() stays
    readable. Translates httpx outcomes into FetchResult.
    """
    try:
        response = client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        return FetchResult(
            url=url,
            status=STATUS_FAILED,
            http_status=None,
            content_type=None,
            body=None,
            error=f"timeout: {exc!s}",
        )
    except httpx.ConnectError as exc:
        return FetchResult(
            url=url,
            status=STATUS_FAILED,
            http_status=None,
            content_type=None,
            body=None,
            error=f"connection error: {exc!s}",
        )
    except httpx.RequestError as exc:
        # Catch-all for other transport-level httpx errors (DNS, TLS, etc.)
        return FetchResult(
            url=url,
            status=STATUS_FAILED,
            http_status=None,
            content_type=None,
            body=None,
            error=f"{type(exc).__name__}: {exc!s}",
        )

    # ---- We have a response. Check status, then size. ----
    http_status = response.status_code
    content_type = response.headers.get("content-type")

    # Final URL after any redirects httpx followed.
    final_url = str(response.url)

    if http_status >= 400:
        return FetchResult(
            url=final_url,
            status=STATUS_FAILED,
            http_status=http_status,
            content_type=content_type,
            body=None,
            error=f"HTTP {http_status}",
        )

    body = response.content
    if len(body) > max_bytes:
        return FetchResult(
            url=final_url,
            status=STATUS_FAILED,
            http_status=http_status,
            content_type=content_type,
            body=None,
            error=f"response too large: {len(body)} bytes (cap {max_bytes})",
        )

    return FetchResult(
        url=final_url,
        status=STATUS_SUCCEEDED,
        http_status=http_status,
        content_type=content_type,
        body=body,
        error=None,
    )
