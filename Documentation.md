# Mono-AXIOM — Documentation

The running source of truth for what is actually built and working. Updated incrementally after each feature is confirmed functional.

For the architectural plan and full checklist, see `PRD.md`.

---

## Current state

**Phase:** 2 — `axiom-queue`: in progress (data layer complete; worker, watchdog, dispatcher not yet built)
**Active work:** `axiom-queue/worker.py` is the next implementation step.

---

## Layer status

| Layer | Status | Notes |
|---|---|---|
| `axiom-store` | Complete | TCP-accessible Markdown store with write-through cache, hybrid framing, schema validation, and a matching client. 139 tests passing. End-to-end demo script runs clean against a live server. Phase 2 has additively widened the public surface (schema instances exported, `LocalServer` + `send_request` promoted to `axiom_store.test_utils`). |
| `axiom-queue` | Partial — data layer complete | `ids`, `jobs`, `handlers`, and `retry` modules implemented and tested. Worker loop, watchdog, and dispatcher not yet built. 71 tests passing across the layer. |
| `axiom-fetch` | Stubbed | Package exists, no implementation |
| `axiom-brain` | Stubbed | Package exists, no implementation |
| `axiom-api` | Stubbed | Package exists, no implementation |

---

## What works end to end

**`axiom-store`:** A complete vault store accessible over TCP from any client. Run the server, point any process at it, and read/write/delete/list Markdown files in the vault. Every byte is validated, every write goes through schema checks, every repeated read is served from cache. The vault stays a fully Obsidian-compatible Markdown directory on disk.

**The live demo** (`scripts/demo_axiom_store.py`) walks the seven verbs and assertions against a running server: WRITE with schema validation, READ roundtrip, LIST, SCHEMA_ERROR rejection, path-traversal rejection (BAD_REQUEST), NOT_FOUND, DELETE, and read-after-delete. All pass.

**`axiom-queue` data layer:** Job creation, frontmatter roundtrip, and storage through `StoreClient` all work end to end. A `create_pending_job("echo", payload={...})` call produces a valid `Job` in memory; `write_job` persists it as a schema-validated `.md` file in `mono-vault/jobs/`; `read_job` reads it back into an equal `Job` instance. Worker code that consumes these primitives is the next step.

### Components

#### axiom-store

- **`axiom-store/frontmatter.py`** — `parse_frontmatter(text) -> (dict, str)` and `render_frontmatter(metadata, body) -> str`. Pure string transforms. `FrontmatterError` (subclass of `ValueError`) on malformed YAML, unclosed fences, or non-mapping YAML. Roundtrip property `parse(render(m, b)) == (m, b)` holds for all tested cases.
- **`axiom-store/filesystem.py`** — `VaultFS` class wrapping a configured vault root. `read`, `write`, `delete`, `list_dir`. Vault-relative paths only; `_resolve` rejects empty/absolute/null-byte/backslash/non-string paths and any path resolving outside the root via `Path.resolve()` + `is_relative_to(root)`. Writes auto-create parent directories. `list_dir` returns sorted filenames, files only. Direct `write_bytes` (atomic-rename deferred per single-writer assumption).
- **`axiom-store/cache.py`** — `CachedVaultStore` wraps a `VaultFS` with `dict[str, bytes]`. Read hit returns from memory; miss reads from disk and populates. Write goes to disk first, then updates the cache. Delete evicts. `list_dir` passes through (not cached). Observable hit/miss counters via `store.stats`. Out-of-band edits not detected (documented Phase 1 limitation, regression-pinned).
- **`axiom-store/schema.py`** — Per-content-type schemas (`FACT`, `SUMMARY`, `CONVERSATION`, `PERSONA`, `JOB`, `FETCH_SOURCE`, `FETCH_CHUNK`) with required/optional keys typed by Python `type`. Longest-prefix registry lookup via `schema_for(vault_path)`. `validate(metadata, schema)` raises `SchemaError` on missing required keys, type mismatches, or unknown keys (unless `allow_extra=True`). Free-form areas (`system/`, `exports/`, `fetch/uploads/`) deliberately have no schema and pass through unvalidated. **JOB schema rewritten for Phase 2** — see "Phase 2 progress" below.
- **`axiom-store/protocol.py`** — Hybrid framing on the wire: `\n`-delimited header lines, blank line, length-prefixed body. Pure-function parsers and formatters: `parse_request_headers`, `parse_response_headers`, `format_request`, `format_response`. Headers are case-sensitive lowercase. `content-length: <n>` is required. `MAX_BODY_BYTES = 10 MB` cap.
- **`axiom-store/server.py`** — `serve_forever(vault_root, host, port)` runs the accept loop. Single-threaded, sequential, one-shot connections. `SO_REUSEADDR` for clean restarts. `recv_until` returns `(before, after)` from header reads so any body bytes coalesced into the same `recv` get prepended to the body read via `recv_exact(initial=after)` — this is the production fix for the framing problem we walked in concept and felt empirically in B2. Pure-function `dispatch(store, request) -> response` translates layer exceptions to protocol statuses (`InvalidVaultPath` → `BAD_REQUEST`, `FileNotFoundError` → `NOT_FOUND`, `SchemaError`/`FrontmatterError` → `SCHEMA_ERROR`, everything else logged → `SERVER_ERROR`). Runs as `python -m axiom_store.server --vault <path>`.
- **`axiom-store/client.py`** — `StoreClient(host, port, timeout)` mirrors `CachedVaultStore`'s interface: `read`, `write`, `delete`, `list_dir`. Connection-per-call (one-shot). Server statuses translate back into Python exceptions matching what the in-process store would raise: `NOT_FOUND` → `FileNotFoundError`, `BAD_REQUEST` → `InvalidVaultPath`, `SCHEMA_ERROR` → `SchemaError`, `SERVER_ERROR` → `StoreError`. **Substitutable** — anywhere a `CachedVaultStore` is acceptable, a `StoreClient` works as a drop-in.
- **`axiom-store/test_utils.py`** — `LocalServer` class and `send_request` helper, promoted from `axiom-store/tests/test_server.py` during Phase 2. Public, importable as `from axiom_store.test_utils import LocalServer, send_request`. Used by Phase 1 tests (`test_server.py`, `test_client.py`) and Phase 2 tests (`test_jobs.py`). Single source of truth for live-server test setup across the repo.

#### axiom-queue

- **`axiom-queue/ids.py`** — `new_job_id()` returns a UUID4 string; `now_iso()` returns the current UTC time as `YYYY-MM-DDTHH:MM:SSZ`. Centralized so tests can monkeypatch a single source for deterministic IDs and timestamps. The `Z` suffix (rather than `+00:00`) is the vault's canonical UTC marker — short, unambiguous, and lexicographically sortable with other timestamps in the same format.
- **`axiom-queue/jobs.py`** — `Job` dataclass mirroring the JOB schema exactly. `__post_init__` validates against the schema via `validate(self.to_frontmatter(), JOB)` — you cannot construct an invalid `Job` in memory. `to_frontmatter()` omits `None`-valued optional fields entirely, keeping pending-job files minimal. `from_frontmatter(md)` is the reverse direction with an unknown-key check (defense in depth — the schema rejects on write, this rejects on read). `create_pending_job(kind, payload, max_attempts=3)` is the factory for new jobs. `write_job`, `read_job`, `list_jobs` are thin wrappers around `StoreClient` that route to `jobs/<id>.md`. Status vocabulary constants (`STATUS_PENDING`, `STATUS_RUNNING`, `STATUS_SUCCEEDED`, `STATUS_FAILED`, `STATUS_DEAD`) and `ALL_STATUSES` are module-level — the dataclass rejects any unknown status.
- **`axiom-queue/handlers.py`** — Handler registry: `HANDLERS: dict[str, Handler]`. Two starter handlers shipped — `echo_handler(payload)` returns `{"echoed": payload["message"]}`, `noop_handler(payload)` returns `{"ok": True}`. `register(kind, handler)` adds, `unregister(kind)` removes, `dispatch(kind, payload)` looks up and runs. `UnknownJobKind` raised when no handler matches; `HandlerError` raised when a handler returns a non-dict (handler contract violation, distinct from a handler raising — those propagate so the worker can decide whether to retry). The registry is module-level mutable; tests use a snapshot/restore fixture to isolate.
- **`axiom-queue/retry.py`** — Pure retry policy. `compute_backoff(attempts, base=1.0, cap=300.0, jitter=False, rng=None)` does exponential backoff with a 5-minute cap and optional ±25% jitter (rng injectable for deterministic tests). `RetryDecision` dataclass carries `next_status`, `next_attempt_at`, and `delay_seconds`. `decide_after_success()` returns the terminal succeeded decision. `decide_after_failure(attempts, max_attempts, jitter, rng)` returns either a `failed` decision with a future `next_attempt_at`, or a `dead` decision if `attempts >= max_attempts`. `is_ready_to_retry(next_attempt_at, now)` lexicographically compares the two ISO 8601 strings — works because all vault timestamps are fixed-width UTC with `Z` suffix; pinned with a regression test.

### Surviving Phase 0 artifacts

- `scratch/parse_frontmatter.py` — B1 (superseded by `axiom-store/frontmatter.py`; retained as Phase 0 exercise reference)
- `scratch/echo_server.py` + `scratch/echo_client.py` — B2 (superseded conceptually by `axiom-store/server.py` and `axiom-store/client.py`; retained because they're where the framing problem was felt empirically before being solved deliberately)

---

## What's confirmed in place

**Repository**

- `git@github.com:disposably-mono/mono-AXIOM.git` — public, Apache 2.0, branch `main`
- Cloned locally at `~/projects/mono-axiom/`

**Scaffold (committed and pushed)**

- Five layer packages — `axiom-store`, `axiom-queue`, `axiom-fetch`, `axiom-brain`, `axiom-api` — each with stub `__init__.py` and `README.md` (the first two now have real implementations)
- `pyproject.toml` — workspace config, hyphen filesystem names mapped to underscore Python import names via explicit `[tool.setuptools] packages` + `package-dir` (auto-discovery via `find` does not work with the flat per-layer layout). Runtime deps: `PyYAML>=6.0`. `testpaths` enumerates per-layer `tests/` directories.
- `.gitignore` — covers Python, secrets (`mono-vault/`, `.env`), editor and OS artifacts
- `.env.example` — placeholders for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `VAULT_PATH`, `STORE_PORT`, `API_PORT`
- `LICENSE` — Apache 2.0
- `README.md` — project overview and layer table
- `scripts/bootstrap_vault.py` — idempotent, copies `mono-vault.example/` to real vault location
- `scripts/demo_axiom_store.py` — end-to-end demo against a live server

**Vault skeleton (`mono-vault.example/`, committed)**

- Full directory structure per PRD §4
- Per-folder `README.md` with documented frontmatter schemas for every content type
- `system/` designated for plain Markdown system docs (no frontmatter)

**Vault (local, gitignored)**

- `mono-vault/` bootstrapped at `~/projects/mono-axiom/mono-vault/`
- `mono-vault/system/PRD.md` and `mono-vault/system/Documentation.md` copied in manually

**Scratch directory**

- `scratch/parse_frontmatter.py`, `scratch/echo_server.py`, `scratch/echo_client.py` — Phase 0 exercise references

**`axiom-store` package (complete)**

- `axiom-store/__init__.py` — re-exports the public surface. Phase 2 additions: schema instances (`CONVERSATION`, `FACT`, `FETCH_CHUNK`, `FETCH_SOURCE`, `JOB`, `PERSONA`, `SUMMARY`) and the test-utility surface stay in `axiom_store.test_utils` rather than `__init__`.
- `axiom-store/frontmatter.py` — frontmatter parse/render
- `axiom-store/filesystem.py` — `VaultFS` class, path discipline, all disk I/O for the vault
- `axiom-store/cache.py` — `CachedVaultStore` write-through cache
- `axiom-store/schema.py` — per-content-type schema definitions and `validate`. `JOB` schema rewritten in Phase 2.
- `axiom-store/protocol.py` — hybrid framing (parse/format, pure functions)
- `axiom-store/server.py` — accept loop, `recv_until` + `recv_exact`, `dispatch`, CLI entry point
- `axiom-store/client.py` — `StoreClient` with status-to-exception translation
- `axiom-store/test_utils.py` — `LocalServer`, `send_request`. Public test utility, importable across layers.
- `axiom-store/tests/test_frontmatter.py` — 18 tests
- `axiom-store/tests/test_filesystem.py` — 29 tests
- `axiom-store/tests/test_cache.py` — 16 tests
- `axiom-store/tests/test_schema.py` — 21 tests (12 original + 9 new JOB tests pinning the Phase 2 shape and the old shape's rejection)
- `axiom-store/tests/test_protocol.py` — 17 tests
- `axiom-store/tests/test_dispatch.py` — 13 tests (pure dispatch, in-memory)
- `axiom-store/tests/test_server.py` — 8 tests (real TCP, real socket, real round trip; now uses `LocalServer` from `axiom_store.test_utils`)
- `axiom-store/tests/test_client.py` — 11 tests (real server + real client + status translation; now uses `LocalServer` from `axiom_store.test_utils`)
- **Total: 139 passing.** (Phase 1: 130 → 139 after JOB schema migration tests.)

**`axiom-queue` package (data layer complete)**

- `axiom-queue/__init__.py` — re-exports `Job`, `JobValidationError`, `create_pending_job`, `list_jobs`, `read_job`, `write_job`, `HANDLERS`, `Handler`, `HandlerError`, `UnknownJobKind`, `dispatch`, `echo_handler`, `noop_handler`, `register`, `unregister`, `BASE_DELAY_SECONDS`, `JITTER_FRACTION`, `MAX_DELAY_SECONDS`, `RetryDecision`, `compute_backoff`, `decide_after_failure`, `decide_after_success`, `is_ready_to_retry`
- `axiom-queue/ids.py` — UUID4 + ISO 8601 helpers
- `axiom-queue/jobs.py` — `Job` dataclass, frontmatter roundtrip, `StoreClient` I/O, `create_pending_job` factory
- `axiom-queue/handlers.py` — registry + `echo` and `noop` starter handlers + `dispatch`
- `axiom-queue/retry.py` — `compute_backoff`, `RetryDecision`, `decide_after_*`, `is_ready_to_retry`
- `axiom-queue/tests/test_jobs.py` — 22 tests
- `axiom-queue/tests/test_retry.py` — 29 tests
- `axiom-queue/tests/test_handlers.py` — 20 tests
- **Total: 71 passing.**

**Repo-wide test count: 210 passing.**

**Decisions locked (Phase 1)**

- Vault repo strategy: Option B — monorepo, vault gitignored, example skeleton committed
- `system/` docs (`PRD.md`, `Documentation.md`) are plain Markdown, no frontmatter, never queried programmatically
- No `/public` folder — vault is the canonical home for living documents
- No per-file Apache 2.0 headers — `LICENSE` at repo root only
- Phase 0 exercises live in `scratch/`; clean implementations enter the layer packages in their respective phases
- Phase 1 framing protocol: hybrid (delimiter-framed `\n` headers + length-prefixed body, HTTP-style). One-shot connections
- Per-layer flat layout (e.g., `axiom-store/frontmatter.py`, not `axiom-store/axiom_store/frontmatter.py`). Tests live inside each layer under `<layer>/tests/`
- `axiom-store` cache strategy: write-through, lazy population, no lock (justified by single-process + one-shot TCP serializing requests). Cache holds `dict[str, bytes]` keyed by vault-relative path
- `axiom-store` filesystem layer is a class (`VaultFS`), not free functions. Cache layer is a class (`CachedVaultStore`) wrapping `VaultFS`. Client is a class (`StoreClient`) substitutable for `CachedVaultStore`. The whole layer composes via the wrapper pattern
- `list_dir` returns regular files only, no subdirectories, sorted alphabetically. Subdir listing deferred until a use case appears
- Phase 1 writes use direct `write_bytes`, not atomic write-temp-then-rename. Single-writer assumption holds for now
- Server binds to `127.0.0.1:7070` by default. `0.0.0.0` is deliberately not the default — the protocol has no authentication
- Headers on the wire are case-sensitive lowercase. `Content-Length: 5` would be a protocol error; `content-length: 5` is the only acceptable spelling
- `MAX_BODY_BYTES = 10 MB`, `MAX_HEADER_BYTES = 8 KB`. Both enforced at protocol-parse time before any further work happens
- Client-side errors are real Python exceptions, not status strings. This is what makes `StoreClient` substitutable for `CachedVaultStore` from a caller's perspective

**Decisions locked (Phase 2 — data layer)**

- **JOB schema (rewritten for Phase 2):** required keys are `id`, `kind`, `status`, `created_at`, `updated_at`, `attempts`, `max_attempts`, `payload`. Optional: `result`, `error`, `next_attempt_at`, `worker_id`, `claimed_at`, `tags`. The old shape (`type`, `created`, `last_error`, `result_path`, `scheduled_for`) is rejected — regression tests pin this.
- **`type` vs `kind` divergence:** other content types use `type` as the discriminator; jobs use `kind`. Deliberate divergence, accepted to avoid carrying both.
- **Status vocabulary:** `pending`, `running`, `succeeded`, `failed`, `dead`. `dead` is unambiguously terminal.
- **`max_attempts` default:** 3.
- **Stall threshold:** 5 minutes fixed for Phase 2. Per-job `timeout` field deferred until a job kind actually needs it.
- **Watchdog cadence:** 10s scan interval (will be applied in `watchdog.py` when built).
- **Retry policy:** exponential backoff, `base = 1s`, `cap = 300s` (5 minutes), optional ±25% jitter (off by default for single-worker Phase 2, will be turned on for multi-worker Phase 4+).
- **`Job` validates twice on write:** once in `__post_init__` (Job in memory cannot be invalid), once on the store side (defense in depth — manual frontmatter writes still get caught).
- **Handler contract:** `payload: dict -> result: dict`. Handlers raise to signal failure (worker retries). Returning a non-dict raises `HandlerError`.
- **Handler registry is module-level mutable** so Phase 3+ layers can register their own kinds at import time. Tests use snapshot/restore fixtures to isolate.
- **`UnknownJobKind` is a fatal failure for the job, not a retryable one** — a missing handler isn't transient (worker logic to be implemented in `worker.py`).
- **Lexicographic timestamp comparison.** `is_ready_to_retry` compares ISO 8601 strings directly. Safe because the format is fixed-width UTC with `Z`. Regression-pinned.
- **Public surface widening in `axiom_store`:** schema instances (`JOB`, `FACT`, `SUMMARY`, `CONVERSATION`, `PERSONA`, `FETCH_SOURCE`, `FETCH_CHUNK`) re-exported. Sets the rule that schema instances are public for all consumers, not just `axiom-queue`.
- **`LocalServer` and `send_request` promoted** from `axiom-store/tests/test_server.py` (where they were file-private) into `axiom_store.test_utils`. Public, importable, single source of truth for live-server tests across all layers.
- **Rootless test layout adopted.** No `__init__.py` in `axiom-store/tests/` or `axiom-queue/tests/`. Avoids the `tests.*` namespace collision pytest creates when multiple package-shaped test directories exist in one repo. Phase 3, 4, 5 test directories also won't have `__init__.py`.

---

## Phase 0 progress

**Concept track — complete (by walkthrough, not by external reading):**

- TCP fundamentals — layered model, why TCP over UDP, what TCP guarantees and doesn't, byte-stream vs message-stream
- Sockets API — `socket`/`bind`/`listen`/`accept`/`connect`/`recv`/`sendall`, listener vs client sockets, blocking semantics, `bytes` vs `str`
- The framing problem — short reads, coalesced messages, split boundaries; delimiter framing, length-prefix framing, hybrid framing; `recv_exact` pattern. Reinforced empirically by B2 and then again by a real coalescing bug fixed during step 6
- YAML frontmatter — fence detection, `yaml.safe_load`, splitting parsing from validation, `safe_load` vs `load`
- Write-through caching — write-through vs write-back vs write-around, the cache invariant, why `axiom-store` doesn't need a lock

**Exercises — both complete:**

- B1 — `parse_frontmatter`: `scratch/parse_frontmatter.py`. Re-implemented cleanly in `axiom-store/frontmatter.py` during Phase 1 step 1
- B2 — TCP echo: `scratch/echo_server.py` + `scratch/echo_client.py`. Proved the socket lifecycle; the framing problem failure modes observed here directly informed `recv_until` + `recv_exact` in production

**External readings on the Phase 0 checklist — not yet done:**

- Kurose chapters 1, 2.1–2.4, 3.1–3.4
- Beazley "Python Concurrency from the Ground Up" (PyCon 2015)
- Beej's Guide chapters 1–5
- Python `socket`, `asyncio`, `multiprocessing` docs
- YAML 1.2 spec + `pyyaml` docs

Most of what these would teach has now been encountered in practice during Phases 1 and 2 (data layer). Reading them remains valuable for reinforcement and depth but is no longer on the critical path.

---

## Phase 1 progress

**Status:** complete.

**Concepts walked (across the phase):**

- Three framing protocols compared in detail — delimiter (escaping problem, scanning cost, max-size guard), length-prefix (`recv_exact`, header-size tradeoffs), hybrid (HTTP-style header + length-prefixed body). Hybrid chosen and implemented.
- Write-through caching applied concretely to `axiom-store` — the cache invariant, why no lock, write/read/delete ordering (disk before cache), the human-edits-the-file wrinkle pinned as a regression marker, lazy vs eager population.
- Python packaging — flat layout vs src layout, hyphen-folder to underscore-import mapping via `[tool.setuptools] packages` + `package-dir` (explicit, not `find`-based discovery), editable installs with `pip install -e ".[dev]"`, per-layer `testpaths` configuration.
- Filesystem layer concerns — path discipline as a security boundary, `Path.resolve()` + `is_relative_to(root)` as the canonical traversal defense, defense in depth via early rejection of obvious garbage.
- Schema design without external libraries — required/optional keys typed by Python `type`, longest-prefix registry, fail-fast `validate` semantics. Choosing not to use `pydantic` or `jsonschema` because the schemas are small and project-internal.
- Protocol-as-pure-functions — separating "parse bytes into a Request" from "read bytes from a socket." The split between `parse_request_headers` returning a `RequestStub` and the server reading the body via `recv_exact` is the load-bearing decision that makes the whole protocol layer trivially testable.
- The wrapper pattern — `CachedVaultStore` wraps `VaultFS`, `StoreClient` is interface-substitutable for both. Composition over inheritance, sketched concretely.
- TCP server practice — accept loop, listener vs connection sockets, `SO_REUSEADDR`, `recv_until` + `recv_exact` with leftover-byte handling, one-shot connection lifecycle, graceful shutdown on `KeyboardInterrupt`.
- The framing bug in stereo — B2 exposed missing bytes (oversized payload truncation), step 6 exposed extra bytes (coalesced header + body). Both are the same problem from opposite sides; both pinned as regression tests.

**Implementation done:**

- All seven steps complete: frontmatter, filesystem, cache, schema, protocol, server, client. 130 tests passing originally; 139 after Phase 2's JOB schema migration tests landed in `test_schema.py`. Live end-to-end demo working.

**Checklist items unblocked across the phase:**

- [x] Concept understood: TCP framing problem (message boundaries)
- [x] Concept understood: write-through cache
- [x] Concept understood: YAML frontmatter schema validation
- [x] Implement `parse_frontmatter` and `render_frontmatter` in `axiom-store`
- [x] Implement vault file read/write (filesystem layer)
- [x] Implement in-memory write-through cache
- [x] Implement TCP server (accept connections, handle requests)
- [x] Implement TCP client (used by other layers)
- [x] Define and implement message framing protocol
- [x] Schema validation for all vault content types
- [x] Milestone confirmed: read/write vault entries over TCP without touching filesystem directly

**Phase 1 footprint changes during Phase 2:**
Two Phase 1 surfaces were additively widened by Phase 2's needs. Both are extensions, not behavior changes. Phase 1 tests still pass.

- Schema instances (`JOB`, `FACT`, etc.) re-exported from `axiom_store`.
- `LocalServer` and `send_request` promoted from `axiom-store/tests/test_server.py` into `axiom_store.test_utils`. Phase 1 tests updated to import from the new location. Renamed without the leading underscore (no longer file-private).
- The `JOB` schema itself was rewritten — this is a behavior change on the schema, but the schema was a Phase 1 placeholder pending the Phase 2 design. Regression tests pin the old shape as explicitly rejected.

---

## Phase 2 progress

**Status:** data layer complete. Worker loop, watchdog, and dispatcher not yet built.

**Concepts walked:**

- **The GIL.** Why Python threads serialize CPU work, why multiprocessing is the right model for workers, why processes-with-vault-as-IPC is cleaner than `multiprocessing.Queue` for this project (the vault is the queue; workers are isolated; failure modes are observable on disk).
- **Job state machine.** `pending → running → succeeded` happy path; `running → failed → pending (retry)` for transient failures; `failed → dead` once `attempts >= max_attempts`. `running → pending` for stalled jobs (watchdog reclaim, when built). Each transition has exactly one writer.
- **Idempotency for retries.** Why job IDs need to be stable across retries. Why `succeeded` writes are terminal and re-checked before any retry-claim. Why exponential backoff prevents stampedes on flaky downstreams.
- **The handler registry pattern.** Open for extension, closed for modification. Job kinds are data (strings in YAML), handlers are functions, the registry is a dict. New job kinds in later phases are one new function + one new registry line.
- **Exponential backoff math.** `delay = min(base * 2 ** attempts, cap)`. Why the cap (otherwise minute-30 retries waste hours), why optional jitter (prevents synchronized retries from N workers slamming the downstream). Locked: base=1s, cap=300s, jitter=±25%.
- **Defense in depth on schema validation.** `Job.__post_init__` validates in-memory; the store validates on write. Manual frontmatter edits, partially-constructed jobs, and out-of-band YAML all hit the same schema either way.
- **Lexicographic time comparison.** Fixed-width ISO 8601 UTC with `Z` suffix is lex-sortable. Pinned with a regression test so future timestamp format changes get caught.

**Implementation done:**

- `ids.py`, `jobs.py`, `handlers.py`, `retry.py` — full data layer.
- JOB schema migrated to the Phase 2 shape.
- `axiom_store.test_utils` extracted and adopted by both Phase 1 and Phase 2 tests.

**Checklist items unblocked:**

- [x] Concept understood: GIL and why multiprocessing over threading for CPU work
- [x] Concept understood: IPC between main process and workers (vault-as-IPC, walked but not yet implemented)
- [x] Concept understood: idempotency and why it matters for retries
- [x] Implement job file creation in `mono-vault/jobs/` (via `create_pending_job` + `write_job`)

**Checklist items still open:**

- [ ] Implement worker process pool
- [ ] Implement job pickup (worker reads pending job files)
- [ ] Implement retry logic with exponential backoff (math implemented in `retry.py`; loop integration pending in `worker.py`)
- [ ] Implement job status updates (written back to vault via `axiom-store`)
- [ ] Milestone confirmed: submit a job, worker executes, result lands in vault

---

## What's documented but not yet implemented

Everything in the PRD beyond `axiom-queue`'s data layer. Next implementation steps within Phase 2: `worker.py` (the loop), `watchdog.py` (stall reclaim), `dispatcher.py` (CLI entry point + multi-worker spawning).

---

## Open questions / deferred decisions

- Frontend framework for `axiom-api` — React vs vanilla JS, deferred to Phase 5
- Embedding model and vector index strategy for `axiom-fetch` — deferred to Phase 3
- `scripts/sync_vault_docs.py` — copy PRD + Documentation into `mono-vault/system/` on demand. Phase 1 manages this with a one-line `cp`; worth scripting if doc updates become more frequent in Phase 2
- Manual vault edits invalidate the in-memory cache. Phase 1 ships with "restart `axiom-store` after manual edits" as the documented workaround. Upgrade to mtime-check on read in Phase 2 or 3 if it becomes annoying in practice — `test_known_limitation_out_of_band_edit_returns_stale` is pinned to fail when the upgrade lands
- Atomic writes (write-temp + fsync + rename) are deferred. Single-writer assumption holds for now. Revisit when concurrent readers or crash-safety become real concerns
- Persistent-connection upgrade for the client. One-shot is simple and works; if loopback overhead ever shows up in profiling, the upgrade path is documented (server-side connection loop, client-side connection pool). Not a Phase 2 concern
- Per-job `timeout` field on jobs. Phase 2 ships with a fixed 5-minute stall threshold. When a job kind needs a different bound (long PDF chunking in Phase 3, slow LLM calls in Phase 4), promote the timeout into the JOB schema as an optional field.
- Watchdog detection of stuck `pending` jobs. Currently only `running` jobs can stall (worker crashed mid-claim). A bug in the dispatcher that loses pending-jobs is theoretically possible; not addressed in Phase 2.

---

## Local environment

| Item | Value |
|---|---|
| OS | Fedora 44 |
| Python | 3.14+ |
| Editors | Neovim + VS Code |
| Hardware | Lenovo IdeaPad Gaming 3 — i5-11320H, 16GB RAM, RTX 3050 Ti Mobile (4GB VRAM) |
| Local model | Qwen3 4B Q4_K_M via Ollama (not yet installed — needed for Phase 4) |

---

*This file is updated only after features are confirmed working. Do not pre-document unbuilt work.*
