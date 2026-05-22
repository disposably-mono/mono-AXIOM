"""
Handler registry for axiom-queue.

A handler is a function that takes a job's payload dict and returns a
result dict. It doesn't know about job IDs, retries, the vault, or any
other job lifecycle concerns. It just runs business logic.

The worker dispatches jobs to handlers by looking up `job.kind` in
HANDLERS. Adding a new job kind in later phases is one line in the
registry plus one new function.

Phase 2 ships with two trivial handlers (`echo` and `noop`) so the
worker has something to actually execute end-to-end. Real handlers
(`fetch_url`, `summarize_context`, etc.) land in Phase 3 and 4.
"""

from __future__ import annotations

from typing import Any, Callable

Handler = Callable[[dict[str, Any]], dict[str, Any]]


class UnknownJobKind(ValueError):
    """Raised when no handler is registered for a job's kind."""


class HandlerError(RuntimeError):
    """
    Raised when a handler's contract is violated (e.g. returns a
    non-dict). Distinguished from exceptions raised *by* a handler,
    which the worker treats as ordinary job failures.
    """


# ----------------------------------------------------------------------
# Starter handlers
# ----------------------------------------------------------------------
def echo_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Trivial handler — returns the input as the result. Used for
    end-to-end testing of the queue without involving any real work.
    """
    return {"echoed": payload.get("message", "")}


def noop_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Even more trivial — always returns {"ok": True}. Used to verify
    the queue pipeline works with a handler that ignores its payload.
    """
    return {"ok": True}


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------
HANDLERS: dict[str, Handler] = {
    "echo": echo_handler,
    "noop": noop_handler,
}


def register(kind: str, handler: Handler) -> None:
    """
    Register a handler for a job kind. Used by tests and (eventually)
    by later layers to add their own handler kinds.

    Raises:
        ValueError: if `kind` is already registered. Re-registration is
        not allowed — tests should use unregister() to clean up.
    """
    if not isinstance(kind, str) or not kind:
        raise ValueError(f"kind must be a non-empty string, got {kind!r}")
    if kind in HANDLERS:
        raise ValueError(f"handler already registered for kind {kind!r}")
    HANDLERS[kind] = handler


def unregister(kind: str) -> None:
    """
    Remove a handler from the registry. Mostly used by tests to clean
    up after register() calls. Raises KeyError if not present.
    """
    del HANDLERS[kind]


def dispatch(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Look up the handler for `kind` and run it against `payload`.

    Raises:
        UnknownJobKind: no handler registered for this kind.
        HandlerError: handler returned something other than a dict.

    Any exception RAISED BY the handler propagates out unchanged —
    that's how the worker decides whether to retry. Don't catch it here.
    """
    handler = HANDLERS.get(kind)
    if handler is None:
        raise UnknownJobKind(
            f"no handler registered for kind {kind!r}; known kinds: {sorted(HANDLERS)}"
        )
    result = handler(payload)
    if not isinstance(result, dict):
        raise HandlerError(
            f"handler for kind {kind!r} returned {type(result).__name__}, expected dict"
        )
    return result
