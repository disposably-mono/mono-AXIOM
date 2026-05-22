# axiom-queue

**Layer 2 — Job dispatch.**

Background work scheduler with worker management and retry logic. Used by other layers to defer long-running operations (web fetches, model calls, batch summarization).

## Responsibility

- Accept and persist job submissions (as `.md` files in `/mono-vault/jobs/`)
- Run the worker loop and watchdog service
- Implement retries, timeouts, and failure handling
- Expose job status to callers

## Status

Phase 2 in progress.

Implemented:
- Job dataclass and vault persistence helpers
- Handler registry with `echo` and `noop` starter handlers
- Exponential retry policy
- Worker loop for claim/execute/resolve
- Watchdog loop for reclaiming stalled `running` jobs
- Dispatcher CLI and pidfile lifecycle guard

Run the dispatcher against a live `axiom-store` server:

```bash
python -m axiom_queue.dispatcher --host 127.0.0.1 --port 7070
```

Or, after reinstalling the editable package:

```bash
axiom-queue --host 127.0.0.1 --port 7070
```
