"""
Tests for axiom_queue.dispatcher.

The dispatcher is mostly lifecycle glue, so these tests focus on:
  - pidfile behavior
  - service start/stop
  - end-to-end processing through the dispatcher loop
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest
from axiom_queue.dispatcher import (
    DispatcherAlreadyRunning,
    acquire_pidfile,
    default_pidfile_path,
    is_process_alive,
    read_pidfile,
    release_pidfile,
    run_dispatcher,
    start_queue_service,
    stop_queue_service,
)
from axiom_queue.jobs import STATUS_SUCCEEDED, create_pending_job, read_job, write_job
from axiom_store import StoreClient
from axiom_store.test_utils import LocalServer


@pytest.fixture
def live_store(tmp_path: Path):
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    server = LocalServer(tmp_path).start()
    client = StoreClient(host=server.host, port=server.port)
    try:
        yield client
    finally:
        server.stop()


def test_default_pidfile_uses_xdg_cache_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert default_pidfile_path() == tmp_path / "cache" / "mono-axiom" / "axiom-queue.pid"


def test_read_pidfile_missing_returns_none(tmp_path: Path):
    assert read_pidfile(tmp_path / "missing.pid") is None


def test_read_pidfile_malformed_returns_none(tmp_path: Path):
    path = tmp_path / "bad.pid"
    path.write_text("not-a-pid\n", encoding="utf-8")
    assert read_pidfile(path) is None


def test_acquire_pidfile_writes_pid(tmp_path: Path):
    path = tmp_path / "queue.pid"
    acquire_pidfile(path, pid=12345)
    assert read_pidfile(path) == 12345


def test_acquire_pidfile_rejects_live_process(tmp_path: Path):
    path = tmp_path / "queue.pid"
    path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    with pytest.raises(DispatcherAlreadyRunning):
        acquire_pidfile(path)


def test_acquire_pidfile_replaces_stale_pid(tmp_path: Path):
    path = tmp_path / "queue.pid"
    path.write_text("999999999\n", encoding="utf-8")
    acquire_pidfile(path, pid=12345)
    assert read_pidfile(path) == 12345


def test_release_pidfile_removes_only_matching_pid(tmp_path: Path):
    path = tmp_path / "queue.pid"
    path.write_text("12345\n", encoding="utf-8")
    release_pidfile(path, pid=999)
    assert path.exists()

    release_pidfile(path, pid=12345)
    assert not path.exists()


def test_is_process_alive_current_pid():
    assert is_process_alive(os.getpid()) is True


def test_start_and_stop_queue_service(live_store: StoreClient):
    stop = threading.Event()
    service = start_queue_service(
        live_store,
        worker_id="dispatcher-test-worker",
        stop_event=stop,
        poll_interval=0.05,
        scan_interval=0.05,
        threshold_seconds=1.0,
    )

    assert service.worker_thread.is_alive()
    assert service.watchdog_thread.is_alive()

    stop_queue_service(service, join_timeout=2.0)
    assert not service.worker_thread.is_alive()
    assert not service.watchdog_thread.is_alive()


def test_run_dispatcher_processes_job_and_releases_pidfile(
    live_store: StoreClient,
    tmp_path: Path,
):
    job = create_pending_job("echo", payload={"message": "hello"})
    write_job(live_store, job)

    stop = threading.Event()
    pidfile = tmp_path / "queue.pid"
    thread = threading.Thread(
        target=run_dispatcher,
        kwargs={
            "client": live_store,
            "worker_id": "dispatcher-test-worker",
            "stop_event": stop,
            "pidfile_path": pidfile,
            "poll_interval": 0.05,
            "scan_interval": 0.05,
            "threshold_seconds": 1.0,
        },
        daemon=True,
    )
    thread.start()

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if read_job(live_store, job.id).status == STATUS_SUCCEEDED:
            break
        time.sleep(0.05)

    stop.set()
    thread.join(timeout=2.0)

    resolved = read_job(live_store, job.id)
    assert resolved.status == STATUS_SUCCEEDED
    assert resolved.result == {"echoed": "hello"}
    assert not thread.is_alive()
    assert not pidfile.exists()
