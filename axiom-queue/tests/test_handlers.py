"""
Tests for axiom_queue.handlers.

Two layers of behavior to cover:
  - The two starter handlers (echo, noop) — payload in, result out.
  - The registry — register, unregister, dispatch, unknown kinds,
    contract violations.

The registry is module-level mutable state. Tests that mutate it use
a fixture that snapshots HANDLERS and restores it after.
"""

from __future__ import annotations

import pytest

from axiom_queue import handlers
from axiom_queue.handlers import (
    HANDLERS,
    HandlerError,
    UnknownJobKind,
    dispatch,
    echo_handler,
    noop_handler,
    register,
    unregister,
)


@pytest.fixture
def isolated_registry():
    """
    Snapshot HANDLERS before the test and restore it after, so tests
    that register/unregister don't leak across each other.
    """
    snapshot = dict(HANDLERS)
    try:
        yield
    finally:
        HANDLERS.clear()
        HANDLERS.update(snapshot)


# ======================================================================
# Starter handlers
# ======================================================================
class TestEchoHandler:
    def test_echoes_message(self):
        assert echo_handler({"message": "hello"}) == {"echoed": "hello"}

    def test_missing_message_returns_empty(self):
        assert echo_handler({}) == {"echoed": ""}

    def test_ignores_extra_keys(self):
        assert echo_handler({"message": "hi", "other": 42}) == {"echoed": "hi"}

    def test_returns_dict(self):
        # Contract: handlers always return dicts.
        assert isinstance(echo_handler({"message": "hi"}), dict)


class TestNoopHandler:
    def test_returns_ok_true(self):
        assert noop_handler({}) == {"ok": True}

    def test_ignores_payload(self):
        assert noop_handler({"junk": "data"}) == {"ok": True}


# ======================================================================
# Registry — register / unregister
# ======================================================================
class TestRegister:
    def test_register_adds_handler(self, isolated_registry):
        def custom(payload):
            return {"custom": True}

        register("custom", custom)
        assert "custom" in HANDLERS
        assert HANDLERS["custom"] is custom

    def test_register_rejects_duplicate(self, isolated_registry):
        def h1(payload):
            return {}

        register("dup", h1)
        with pytest.raises(ValueError, match="already registered"):
            register("dup", h1)

    def test_register_rejects_empty_kind(self, isolated_registry):
        with pytest.raises(ValueError, match="non-empty string"):
            register("", lambda p: {})

    def test_register_rejects_non_string_kind(self, isolated_registry):
        with pytest.raises(ValueError, match="non-empty string"):
            register(42, lambda p: {})  # type: ignore[arg-type]


class TestUnregister:
    def test_unregister_removes_handler(self, isolated_registry):
        def custom(payload):
            return {}

        register("custom", custom)
        unregister("custom")
        assert "custom" not in HANDLERS

    def test_unregister_unknown_raises(self, isolated_registry):
        with pytest.raises(KeyError):
            unregister("never-registered")


# ======================================================================
# dispatch
# ======================================================================
class TestDispatch:
    def test_dispatch_echo(self):
        result = dispatch("echo", {"message": "hi"})
        assert result == {"echoed": "hi"}

    def test_dispatch_noop(self):
        result = dispatch("noop", {})
        assert result == {"ok": True}

    def test_dispatch_unknown_kind_raises(self):
        with pytest.raises(UnknownJobKind, match="no handler registered"):
            dispatch("not-a-real-kind", {})

    def test_dispatch_unknown_kind_lists_known_in_message(self):
        # The error message should help debugging by listing what IS
        # registered.
        with pytest.raises(UnknownJobKind, match="echo"):
            dispatch("not-a-real-kind", {})

    def test_dispatch_propagates_handler_exception(self, isolated_registry):
        # Exceptions raised BY a handler are not caught here. The
        # worker uses them to decide whether to retry.
        def boom(payload):
            raise RuntimeError("kaboom")

        register("boom", boom)
        with pytest.raises(RuntimeError, match="kaboom"):
            dispatch("boom", {})

    def test_dispatch_rejects_non_dict_result(self, isolated_registry):
        def bad(payload):
            return "not a dict"

        register("bad", bad)
        with pytest.raises(HandlerError, match="expected dict"):
            dispatch("bad", {})

    def test_dispatch_rejects_none_result(self, isolated_registry):
        def returns_none(payload):
            return None

        register("none", returns_none)
        with pytest.raises(HandlerError, match="expected dict"):
            dispatch("none", {})

    def test_dispatch_with_custom_handler(self, isolated_registry):
        # The full happy path for a registered custom handler.
        def double(payload):
            return {"doubled": payload["value"] * 2}

        register("double", double)
        assert dispatch("double", {"value": 21}) == {"doubled": 42}


# ======================================================================
# Default registry contents
# ======================================================================
class TestDefaultRegistry:
    def test_echo_in_default_registry(self):
        assert "echo" in HANDLERS

    def test_noop_in_default_registry(self):
        assert "noop" in HANDLERS

    def test_phase2_starter_kinds_only(self):
        # Pin: Phase 2 only has echo and noop. When Phase 3 adds
        # fetch_url, this test must be updated deliberately — that's
        # the trigger to think about whether the new kind needs its
        # own Documentation.md entry.
        assert set(HANDLERS.keys()) == {"echo", "noop"}
