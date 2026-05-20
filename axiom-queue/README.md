# axiom-queue

**Layer 2 — Job dispatch.**

Background work scheduler with worker management and retry logic. Used by other layers to defer long-running operations (web fetches, model calls, batch summarization).

## Responsibility

- Accept and persist job submissions (as `.md` files in `/mono-vault/jobs/`)
- Spawn and manage worker processes
- Implement retries, timeouts, and failure handling
- Expose job status to callers

## Status

Not yet implemented. Phase 2 (Weeks 6–8).
