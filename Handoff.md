# Handoff

Session date: 2026-05-22

## Summary

This session continued Phase 2 of Mono-AXIOM by moving `axiom-queue` from a tested data layer plus worker/watchdog work into a runnable queue service.

The final pushed commit is:

```text
5fa236f feat(axiom-queue): add runnable queue service
```

It was pushed to `origin/main`.

## Starting State

The repository already had:

- A complete `axiom-store` layer.
- A complete `axiom-queue` data layer: `ids.py`, `jobs.py`, `handlers.py`, and `retry.py`.
- Uncommitted local Phase 2 work for:
  - `axiom-queue/worker.py`
  - `axiom-queue/watchdog.py`
  - `axiom-queue/tests/test_worker.py`
  - `axiom-queue/tests/test_watchdog.py`
  - modifications to `axiom-queue/__init__.py`

Those worker/watchdog files were treated as existing project work and preserved.

## Codebase Read

I first read and understood:

- Root docs: `README.md`, `PRD.md`, `Documentation.md`, `pyproject.toml`
- `axiom-store`: frontmatter, filesystem, cache, schema, protocol, server, client, test utilities
- `axiom-queue`: ids, jobs, handlers, retry, worker, watchdog, tests
- Vault skeleton docs in `mono-vault.example/`
- Scripts: `scripts/bootstrap_vault.py`, `scripts/demo_axiom_store.py`

The important discovery was that `Documentation.md` was stale: it said worker/watchdog were not built, but the working tree already contained implementations and tests for them.

## Implemented

### Dispatcher

Added `axiom-queue/dispatcher.py`.

It provides:

- `QueueService` dataclass for worker/watchdog thread handles.
- `DispatcherAlreadyRunning` exception.
- Pidfile helpers:
  - `default_pidfile_path`
  - `read_pidfile`
  - `is_process_alive`
  - `acquire_pidfile`
  - `release_pidfile`
- Queue service lifecycle:
  - `start_queue_service`
  - `stop_queue_service`
  - `run_dispatcher`
- CLI support:
  - `install_signal_handlers`
  - `main`

The dispatcher starts one worker loop and one watchdog loop in threads and coordinates graceful shutdown through a shared `threading.Event`.

The default pidfile is:

```text
$XDG_CACHE_HOME/mono-axiom/axiom-queue.pid
```

or, if `XDG_CACHE_HOME` is unset:

```text
~/.cache/mono-axiom/axiom-queue.pid
```

Phase 2 intentionally remains single-dispatcher / single-worker-per-vault. True multi-worker pooling is deferred until the store grows an atomic claim primitive.

### Dispatcher Tests

Added `axiom-queue/tests/test_dispatcher.py`.

Coverage includes:

- Default pidfile path honors `XDG_CACHE_HOME`.
- Missing and malformed pidfiles are tolerated.
- Pidfile acquisition writes a pid.
- Live pidfile detection rejects a second dispatcher.
- Stale pidfiles are replaced.
- Pidfile release only removes matching pids.
- Current process liveness check.
- Queue service starts/stops worker and watchdog threads.
- End-to-end dispatcher loop processes an `echo` job to `succeeded` and releases the pidfile.

### Package Exports

Updated `axiom-queue/__init__.py`.

It now exports:

- Existing jobs/handlers/retry APIs.
- Worker APIs.
- Watchdog APIs.
- Dispatcher APIs.

Dispatcher exports are lazy-loaded through `__getattr__` so this remains clean:

```bash
python -m axiom_queue.dispatcher --help
```

Without lazy loading, Python emitted a `runpy` warning because `axiom_queue.__init__` imported `axiom_queue.dispatcher` before module execution.

### CLI Entry Point

Updated `pyproject.toml` with:

```toml
[project.scripts]
axiom-queue = "axiom_queue.dispatcher:main"
```

After reinstalling the editable package, the queue dispatcher can be run as:

```bash
axiom-queue --host 127.0.0.1 --port 7070
```

It can also run without reinstalling:

```bash
python -m axiom_queue.dispatcher --host 127.0.0.1 --port 7070
```

## Documentation Updated

Updated repo-level docs:

- `README.md`
- `PRD.md`
- `Documentation.md`
- `axiom-queue/README.md`
- `mono-vault.example/jobs/README.md`

The docs now describe:

- `axiom-store` as complete.
- `axiom-queue` as a runnable Phase 2 queue service.
- Worker claim/execute/resolve behavior.
- Watchdog stalled-job reclaim.
- Dispatcher pidfile and lifecycle behavior.
- The remaining deferred item: true multi-worker process pooling.

Updated vault-level docs too:

- Copied `PRD.md` to `mono-vault/system/PRD.md`
- Copied `Documentation.md` to `mono-vault/system/Documentation.md`

Both copies were verified with `cmp` after syncing.

Note: `mono-vault/` is gitignored, so the vault-level sync is local state and is not represented in git.

## Tests And Checks

Full suite before commit:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
284 passed in 9.41s
```

After the lazy import fix:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
284 passed in 9.21s
```

Targeted Ruff on the newly added/changed dispatcher surface:

```bash
.venv/bin/ruff check axiom-queue/__init__.py axiom-queue/dispatcher.py axiom-queue/tests/test_dispatcher.py
```

Result:

```text
All checks passed!
```

Repo-wide Ruff was also tried. It reported a pre-existing backlog across older Phase 1 and Phase 2 files. I did not auto-fix the whole repo because that would create unrelated churn.

## Git

Committed:

```text
5fa236f feat(axiom-queue): add runnable queue service
```

Pushed:

```text
origin/main
```

There was one transient DNS failure during the first push attempt:

```text
ssh: Could not resolve hostname github.com: No address associated with hostname
```

DNS resolved on retry and the push succeeded.

## Naming And Documentation Conventions

The generated code follows the project conventions already present in the repo:

- Module names use lower snake case: `dispatcher.py`, matching `worker.py`, `watchdog.py`, `jobs.py`, `retry.py`.
- Public functions use clear verb phrases like `run_dispatcher`, `start_queue_service`, `acquire_pidfile`, mirroring existing names such as `run_worker`, `scan_for_claimable_jobs`, `write_job`, and `read_job`.
- Constants use upper snake case: `DEFAULT_HOST`, `DEFAULT_PORT`, `DEFAULT_PIDFILE_NAME`, `DEFAULT_JOIN_TIMEOUT_SECONDS`.
- Exceptions are named as explicit domain errors: `DispatcherAlreadyRunning`, matching existing style such as `UnknownJobKind`, `HandlerError`, and `JobValidationError`.
- Public lifecycle data is represented as a small frozen dataclass: `QueueService`, matching existing dataclass usage for `Job`, `RetryDecision`, `ClaimResult`, and `ExecutionOutcome`.
- File docstrings follow the explanatory style already used in `worker.py`, `watchdog.py`, and `retry.py`.
- Tests use the existing per-layer rootless test layout under `axiom-queue/tests/`.
- Tests use a live `StoreClient` and `LocalServer`, matching the existing worker/watchdog/job tests.
- Documentation was updated in both high-level docs and layer-local README files after implementation was confirmed.

One intentional difference: dispatcher exports in `axiom-queue/__init__.py` are lazy-loaded. This was done to preserve the package public surface while avoiding the `python -m axiom_queue.dispatcher` module-runner warning.

## Current State After This File

This `Handoff.md` file was created after commit `5fa236f` and is intended to be committed with the follow-up demo/path fix commit.

## Suggested Next Steps

1. Decide whether Phase 2 should be marked complete despite deferring true multi-worker pooling, or whether a minimal process-pool wrapper should be built first.
2. Consider a small docs sync script for copying repo docs into `mono-vault/system/`, since this was needed manually.
3. If the single-worker dispatcher is accepted as the Phase 2 milestone, move on to Phase 3 `axiom-fetch`.

## Addendum: Demo Path Fix

After the first successful queue demo, a path confusion surfaced:

- Some old examples pointed at `/home/mono/projects/mono-axiom`.
- The intended repo root is `/home/mono/Projects/mono-axiom`.

Follow-up local changes made after commit `5fa236f`:

- Updated `.env.example` so `VAULT_PATH` uses `/home/mono/Projects/mono-axiom/mono-vault`.
- Updated `scripts/demo_axiom_store.py` docstring to use the uppercase `Projects` path.
- Added `scripts/demo_axiom_queue.py`, which submits an `echo` job, waits for success, and prints the absolute job file path under the repo-root vault.
- Fixed `axiom_queue.jobs.list_jobs` so scaffold `jobs/README.md` is ignored instead of being treated as a malformed job.
- Added a regression test for ignoring `jobs/README.md`.
- Updated `Documentation.md` and `PRD.md` to include the queue demo, root path, README skip behavior, and new test counts.
- Re-synced vault-level `mono-vault/system/PRD.md` and `mono-vault/system/Documentation.md` after doc updates.

Verification:

```text
285 passed in 9.45s
```

Targeted Ruff on the changed queue/demo files passed. Repo-wide Ruff still has older pre-existing style findings outside this slice.
