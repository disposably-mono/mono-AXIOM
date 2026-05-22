"""
Test utilities for axiom-store and downstream layers.

Reusable helpers for tests that need a real running axiom-store server.
Lives inside the axiom-store package (rather than a tests/ directory)
so any layer can import it without fragile sys.path tricks:

    from axiom_store.test_utils import LocalServer, send_request

This module is import-safe in production code paths but should only be
used in tests — it spins up real sockets and threads.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

from axiom_store.cache import CachedVaultStore
from axiom_store.filesystem import VaultFS
from axiom_store.protocol import (
    HEADER_END,
    Request,
    format_request,
    parse_response_headers,
)
from axiom_store.server import handle_connection


def send_request(host: str, port: int, request: Request) -> tuple[str, bytes]:
    """
    Connect, send one request, read one response, return (status, body).
    Mirrors the Phase 1 _send_request helper exactly.
    """
    with socket.create_connection((host, port), timeout=5.0) as sock:
        sock.sendall(format_request(request))
        buf = bytearray()
        while HEADER_END not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
        header_part, _, after = bytes(buf).partition(HEADER_END)
        stub = parse_response_headers(header_part)
        body = bytearray(after)
        while len(body) < stub.content_length:
            chunk = sock.recv(min(4096, stub.content_length - len(body)))
            if not chunk:
                break
            body.extend(chunk)
        return stub.status, bytes(body)


class LocalServer:
    """
    A one-shot axiom-store server running in a daemon thread, bound to
    an ephemeral port. Use for tests that need real TCP behavior.

    Pattern:
        server = LocalServer(tmp_path).start()
        try:
            client = StoreClient(host=server.host, port=server.port)
            # ... test code ...
        finally:
            server.stop()
    """

    def __init__(self, vault_root: Path) -> None:
        self.store = CachedVaultStore(VaultFS(vault_root))
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))  # ephemeral port
        self.host, self.port = self.listener.getsockname()
        self.listener.listen(8)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        # Short accept timeout so we can poll the stop flag.
        self.listener.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except TimeoutError:
                continue
            with conn:
                handle_connection(conn, self.store)
        self.listener.close()

    def start(self) -> LocalServer:
        self._thread.start()
        # Tiny delay to avoid races on the very first connection.
        time.sleep(0.02)
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
