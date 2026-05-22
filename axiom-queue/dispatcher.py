"""
Dispatcher for axiom-queue.

The dispatcher is the runnable Phase 2 queue service. It owns process
lifecycle around the worker and watchdog loops:

  - enforce one dispatcher per vault via a pidfile
  - install SIGINT/SIGTERM handlers in the CLI
  - start the worker and watchdog loops
  - coordinate graceful shutdown with a shared stop_event

Phase 2 deliberately keeps the concurrency boundary small: one dispatcher
process, one worker loop, one watchdog loop. Multi-worker claiming needs
atomic compare-and-set or rename semantics, so it is deferred until the
store grows the right primitive.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from axiom_queue.watchdog import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    STALL_THRESHOLD_SECONDS,
    run_watchdog,
)
from axiom_queue.worker import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    make_worker_id,
    run_worker,
)
from axiom_store import StoreClient

log = logging.getLogger("axiom_queue.dispatcher")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7070
DEFAULT_PIDFILE_NAME = "axiom-queue.pid"
DEFAULT_JOIN_TIMEOUT_SECONDS = 5.0


class DispatcherAlreadyRunning(RuntimeError):
    """Raised when the queue dispatcher pidfile points at a live process."""


@dataclass(frozen=True)
class QueueService:
    """Handles for a running in-process queue service."""

    worker_thread: threading.Thread
    watchdog_thread: threading.Thread
    stop_event: threading.Event


def default_pidfile_path() -> Path:
    """
    Return the default pidfile path under the user's cache directory.

    Uses XDG_CACHE_HOME when present, otherwise ~/.cache. The final path
    is ~/.cache/mono-axiom/axiom-queue.pid by default.
    """
    cache_home = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return root / "mono-axiom" / DEFAULT_PIDFILE_NAME


def read_pidfile(path: Path | str) -> int | None:
    """Read a pidfile. Returns None when missing, empty, or malformed."""
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 0 else None


def is_process_alive(pid: int) -> bool:
    """
    Return True if `pid` appears to be alive.

    POSIX `kill(pid, 0)` performs existence/permission checking without
    sending a signal. PermissionError still means the process exists.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_pidfile(path: Path | str, pid: int | None = None) -> Path:
    """
    Create or replace a pidfile for the current dispatcher.

    If the pidfile already points to a live process, raises
    DispatcherAlreadyRunning. Stale, empty, and malformed pidfiles are
    overwritten.
    """
    target = Path(path)
    current_pid = pid if pid is not None else os.getpid()
    existing = read_pidfile(target)
    if existing is not None and is_process_alive(existing):
        raise DispatcherAlreadyRunning(
            f"axiom-queue dispatcher already running with pid {existing} "
            f"(pidfile: {target})"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{current_pid}\n", encoding="utf-8")
    log.debug("acquired pidfile %s for pid %s", target, current_pid)
    return target


def release_pidfile(path: Path | str, pid: int | None = None) -> None:
    """
    Remove a pidfile if it still belongs to this dispatcher.

    If another process has replaced the pidfile, leave it alone.
    """
    target = Path(path)
    current_pid = pid if pid is not None else os.getpid()
    if read_pidfile(target) != current_pid:
        return
    try:
        target.unlink()
    except FileNotFoundError:
        return
    log.debug("released pidfile %s", target)


def start_queue_service(
    client: StoreClient,
    *,
    worker_id: str | None = None,
    stop_event: threading.Event | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    scan_interval: float = DEFAULT_SCAN_INTERVAL_SECONDS,
    threshold_seconds: float = STALL_THRESHOLD_SECONDS,
) -> QueueService:
    """
    Start worker and watchdog loops in background threads.

    The returned QueueService exposes the shared stop_event. Set it and
    join both threads to shut the service down.
    """
    stop = stop_event or threading.Event()
    resolved_worker_id = worker_id or make_worker_id()

    worker_thread = threading.Thread(
        target=run_worker,
        kwargs={
            "client": client,
            "worker_id": resolved_worker_id,
            "stop_event": stop,
            "poll_interval": poll_interval,
        },
        name="axiom-queue-worker",
        daemon=True,
    )
    watchdog_thread = threading.Thread(
        target=run_watchdog,
        kwargs={
            "client": client,
            "stop_event": stop,
            "scan_interval": scan_interval,
            "threshold_seconds": threshold_seconds,
        },
        name="axiom-queue-watchdog",
        daemon=True,
    )

    worker_thread.start()
    watchdog_thread.start()
    log.info("queue service started (worker_id=%s)", resolved_worker_id)
    return QueueService(
        worker_thread=worker_thread,
        watchdog_thread=watchdog_thread,
        stop_event=stop,
    )


def stop_queue_service(
    service: QueueService,
    join_timeout: float = DEFAULT_JOIN_TIMEOUT_SECONDS,
) -> None:
    """Request shutdown and wait briefly for worker/watchdog threads."""
    service.stop_event.set()
    service.worker_thread.join(timeout=join_timeout)
    service.watchdog_thread.join(timeout=join_timeout)

    if service.worker_thread.is_alive():
        log.warning("worker thread did not exit within %.1fs", join_timeout)
    if service.watchdog_thread.is_alive():
        log.warning("watchdog thread did not exit within %.1fs", join_timeout)


def run_dispatcher(
    client: StoreClient,
    *,
    worker_id: str | None = None,
    stop_event: threading.Event | None = None,
    pidfile_path: Path | str | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    scan_interval: float = DEFAULT_SCAN_INTERVAL_SECONDS,
    threshold_seconds: float = STALL_THRESHOLD_SECONDS,
    join_timeout: float = DEFAULT_JOIN_TIMEOUT_SECONDS,
) -> None:
    """
    Run the queue service until stop_event is set.

    This is the testable, blocking dispatcher core. The CLI wraps it with
    argument parsing and signal handling.
    """
    stop = stop_event or threading.Event()
    pidfile = Path(pidfile_path) if pidfile_path is not None else default_pidfile_path()
    acquire_pidfile(pidfile)

    service: QueueService | None = None
    try:
        service = start_queue_service(
            client,
            worker_id=worker_id,
            stop_event=stop,
            poll_interval=poll_interval,
            scan_interval=scan_interval,
            threshold_seconds=threshold_seconds,
        )
        while not stop.is_set():
            stop.wait(timeout=0.2)
    finally:
        stop.set()
        if service is not None:
            stop_queue_service(service, join_timeout=join_timeout)
        release_pidfile(pidfile)
        log.info("queue dispatcher stopped")


def install_signal_handlers(stop_event: threading.Event) -> None:
    """Install SIGINT/SIGTERM handlers that request graceful shutdown."""

    def _handler(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %s; stopping queue dispatcher", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the axiom-queue dispatcher.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="axiom-store host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="axiom-store port")
    parser.add_argument(
        "--pidfile",
        type=Path,
        default=None,
        help="Pidfile path (default: $XDG_CACHE_HOME/mono-axiom/axiom-queue.pid)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Worker poll interval in seconds",
    )
    parser.add_argument(
        "--scan-interval",
        type=float,
        default=DEFAULT_SCAN_INTERVAL_SECONDS,
        help="Watchdog scan interval in seconds",
    )
    parser.add_argument(
        "--stall-threshold",
        type=float,
        default=STALL_THRESHOLD_SECONDS,
        help="Seconds a running job may remain claimed before watchdog reclaim",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    stop_event = threading.Event()
    install_signal_handlers(stop_event)
    client = StoreClient(host=args.host, port=args.port)

    try:
        run_dispatcher(
            client,
            stop_event=stop_event,
            pidfile_path=args.pidfile,
            poll_interval=args.poll_interval,
            scan_interval=args.scan_interval,
            threshold_seconds=args.stall_threshold,
        )
    except DispatcherAlreadyRunning as e:
        log.error("%s", e)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
