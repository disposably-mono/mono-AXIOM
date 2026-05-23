# Mono-AXIOM — Documentation

The running source of truth for what is actually built and working. Updated incrementally after each feature is confirmed functional.

For the architectural plan and full checklist, see `PRD.md`.

---

## Current state

**Phase:** 3 — `axiom-fetch`: in progress (URL ingestion MVP functional)
**Active work:** Decide whether Phase 3 next grows upload/PDF/DOCX support, a queue handler wrapper, or retrieval-facing search/index plumbing.

---

## Layer status

| Layer | Status | Notes |
|---|---|---|
| `axiom-store` | Complete | TCP-accessible Markdown store with write-through cache, hybrid framing, schema validation, and a matching client. 155 tests passing. End-to-end demo script runs clean against a live server. Phase 2/3 have additively widened the public surface and migrated JOB/FETCH schemas to their real shapes. |
| `axiom-queue` | Runnable service complete | `ids`, `jobs`, `handlers`, `retry`, worker loop, watchdog, dispatcher, and queue demo implemented and tested. Single dispatcher per vault enforced by pidfile. 146 tests passing across the layer. True multi-worker pooling remains deferred until the store has an atomic claim primitive. |
| `axiom-fetch` | Partial — URL ingestion MVP complete | HTTP fetcher, HTML/plain-text extractor, fixed-size overlapping chunker, ID helpers, and vault-writing ingestion pipeline implemented. 119 tests passing. Uploads, PDF/DOCX extraction, embeddings, and retrieval/search remain deferred. |
| `axiom-brain` | Stubbed | Package exists, no implementation |
| `axiom-api` | Stubbed | Package exists, no implementation |

---

## What works end to end

**`axiom-store`:** A complete vault store accessible over TCP from any client. Run the server, point any process at it, and read/write/delete/list Markdown files in the vault. Every byte is validated, every write goes through schema checks, every repeated read is served from cache. The vault stays a fully Obsidian-compatible Markdown directory on disk.

**The live demo** (`scripts/demo_axiom_store.py`) walks the seven verbs and assertions against a running server: WRITE with schema validation, READ roundtrip, LIST, SCHEMA_ERROR rejection, path-traversal rejection (BAD_REQUEST), NOT_FOUND, DELETE, and read-after-delete. All pass.

**`axiom-queue` runnable service:** Job creation, vault persistence, worker execution, retry transitions, watchdog reclaim, and dispatcher lifecycle now work against a live `axiom-store` server. A `create_pending_job("echo", payload={...})` call can be persisted through `write_job`; the dispatcher starts the worker/watchdog loops; the worker claims the job, executes the handler, and writes the `succeeded` result back into `mono-vault/jobs/<id>.md`.

**The queue demo** (`scripts/demo_axiom_queue.py`) submits an `echo` job through the TCP store, waits for the dispatcher/worker to resolve it, then prints the absolute job file path under `/home/mono/Projects/mono-axiom/mono-vault/jobs/`. This pins the intended local repo root and prevents accidental writes to similarly named lowercase paths.

**`axiom-fetch` URL ingestion path:** `ingest(url, store)` writes a pending `fetch/sources/<source_id>.md`, fetches the URL over HTTP, extracts HTML or plain text into Markdown, slices it into overlapping chunks, writes `fetch/chunks/<source_id>-NNNN.md`, then updates the source to `succeeded` or `failed`. Fetch and extraction failures are recorded in vault metadata instead of bubbling as runtime errors; programmer errors still raise `ValueError`. The pipeline is tested with deterministic fake fetches and an in-memory store, so no test reaches the public internet.

### Components

#### axiom-store

- **`axiom-store/frontmatter.py`** — `parse_frontmatter(text) -> (dict, str)` and `render_frontmatter(metadata, body) -> str`. Pure string transforms. `FrontmatterError` (subclass of `ValueError`) on malformed YAML, unclosed fences, or non-mapping YAML. Roundtrip property `parse(render(m, b)) == (m, b)` holds for all tested cases.
- **`axiom-store/filesystem.py`** — `VaultFS` class wrapping a configured vault root. `read`, `write`, `delete`, `list_dir`. Vault-relative paths only; `_resolve` rejects empty/absolute/null-byte/backslash/non-string paths and any path resolving outside the root via `Path.resolve()` + `is_relative_to(root)`. Writes auto-create parent directories. `list_dir` returns sorted filenames, files only. Direct `write_bytes` (atomic-rename deferred per single-writer assumption).
- **`axiom-store/cache.py`** — `CachedVaultStore` wraps a `VaultFS` with `dict[str, bytes]`. Read hit returns from memory; miss reads from disk and populates. Write goes to disk first, then updates the cache. Delete evicts. `list_dir` passes through (not cached). Observable hit/miss counters via `store.stats`. Out-of-band edits not detected (documented Phase 1 limitation, regression-pinned).
- **`axiom-store/schema.py`** — Per-content-type schemas (`FACT`, `SUMMARY`, `CONVERSATION`, `PERSONA`, `JOB`, `FETCH_SOURCE`, `FETCH_CHUNK`) with required/optional keys typed by Python `type`. Longest-prefix registry lookup via `schema_for(vault_path)`. `validate(metadata, schema)` raises `SchemaError` on missing required keys, type mismatches, or unknown keys (unless `allow_extra=True`). Free-form areas (`system/`, `exports/`, `fetch/uploads/`) deliberately have no schema and pass through unvalidated. **JOB schema rewritten for Phase 2; FETCH_SOURCE/FETCH_CHUNK schemas rewritten for Phase 3** — see progress sections below.
- **`axiom-store/protocol.py`** — Hybrid framing on the wire: `\n`-delimited header lines, blank line, length-prefixed body. Pure-function parsers and formatters: `parse_request_headers`, `parse_response_headers`, `format_request`, `format_response`. Headers are case-sensitive lowercase. `content-length: <n>` is required. `MAX_BODY_BYTES = 10 MB` cap.
- **`axiom-store/server.py`** — `serve_forever(vault_root, host, port)` runs the accept loop. Single-threaded, sequential, one-shot connections. `SO_REUSEADDR` for clean restarts. `recv_until` returns `(before, after)` from header reads so any body bytes coalesced into the same `recv` get prepended to the body read via `recv_exact(initial=after)` — this is the production fix for the framing problem we walked in concept and felt empirically in B2. Pure-function `dispatch(store, request) -> response` translates layer exceptions to protocol statuses (`InvalidVaultPath` → `BAD_REQUEST`, `FileNotFoundError` → `NOT_FOUND`, `SchemaError`/`FrontmatterError` → `SCHEMA_ERROR`, everything else logged → `SERVER_ERROR`). Runs as `python -m axiom_store.server --vault <path>`.
- **`axiom-store/client.py`** — `StoreClient(host, port, timeout)` mirrors `CachedVaultStore`'s interface: `read`, `write`, `delete`, `list_dir`. Connection-per-call (one-shot). Server statuses translate back into Python exceptions matching what the in-process store would raise: `NOT_FOUND` → `FileNotFoundError`, `BAD_REQUEST` → `InvalidVaultPath`, `SCHEMA_ERROR` → `SchemaError`, `SERVER_ERROR` → `StoreError`. **Substitutable** — anywhere a `CachedVaultStore` is acceptable, a `StoreClient` works as a drop-in.
- **`axiom-store/test_utils.py`** — `LocalServer` class and `send_request` helper, promoted from `axiom-store/tests/test_server.py` during Phase 2. Public, importable as `from axiom_store.test_utils import LocalServer, send_request`. Used by Phase 1 tests (`test_server.py`, `test_client.py`) and Phase 2 tests (`test_jobs.py`). Single source of truth for live-server test setup across the repo.

#### axiom-queue

- **`axiom-queue/ids.py`** — `new_job_id()` returns a UUID4 string; `now_iso()` returns the current UTC time as `YYYY-MM-DDTHH:MM:SSZ`. Centralized so tests can monkeypatch a single source for deterministic IDs and timestamps. The `Z` suffix (rather than `+00:00`) is the vault's canonical UTC marker — short, unambiguous, and lexicographically sortable with other timestamps in the same format.
- **`axiom-queue/jobs.py`** — `Job` dataclass mirroring the JOB schema exactly. `__post_init__` validates against the schema via `validate(self.to_frontmatter(), JOB)` — you cannot construct an invalid `Job` in memory. `to_frontmatter()` omits `None`-valued optional fields entirely, keeping pending-job files minimal. `from_frontmatter(md)` is the reverse direction with an unknown-key check (defense in depth — the schema rejects on write, this rejects on read). `create_pending_job(kind, payload, max_attempts=3)` is the factory for new jobs. `write_job`, `read_job`, `list_jobs` are thin wrappers around `StoreClient` that route to `jobs/<id>.md`; `list_jobs` skips scaffold `jobs/README.md` so documentation files are not treated as malformed jobs. Status vocabulary constants (`STATUS_PENDING`, `STATUS_RUNNING`, `STATUS_SUCCEEDED`, `STATUS_FAILED`, `STATUS_DEAD`) and `ALL_STATUSES` are module-level — the dataclass rejects any unknown status.
- **`axiom-queue/handlers.py`** — Handler registry: `HANDLERS: dict[str, Handler]`. Two starter handlers shipped — `echo_handler(payload)` returns `{"echoed": payload["message"]}`, `noop_handler(payload)` returns `{"ok": True}`. `register(kind, handler)` adds, `unregister(kind)` removes, `dispatch(kind, payload)` looks up and runs. `UnknownJobKind` raised when no handler matches; `HandlerError` raised when a handler returns a non-dict (handler contract violation, distinct from a handler raising — those propagate so the worker can decide whether to retry). The registry is module-level mutable; tests use a snapshot/restore fixture to isolate.
- **`axiom-queue/retry.py`** — Pure retry policy. `compute_backoff(attempts, base=1.0, cap=300.0, jitter=False, rng=None)` does exponential backoff with a 5-minute cap and optional ±25% jitter (rng injectable for deterministic tests). `RetryDecision` dataclass carries `next_status`, `next_attempt_at`, and `delay_seconds`. `decide_after_success()` returns the terminal succeeded decision. `decide_after_failure(attempts, max_attempts, jitter, rng)` returns either a `failed` decision with a future `next_attempt_at`, or a `dead` decision if `attempts >= max_attempts`. `is_ready_to_retry(next_attempt_at, now)` lexicographically compares the two ISO 8601 strings — works because all vault timestamps are fixed-width UTC with `Z` suffix; pinned with a regression test.
- **`axiom-queue/worker.py`** — Worker loop. `scan_for_claimable_jobs` finds `pending` jobs and `failed` jobs whose `next_attempt_at` has passed. `claim` writes `running`, increments `attempts`, sets `worker_id`/`claimed_at`, and clears prior retry state. `execute` dispatches to the handler registry and classifies unknown kinds / handler contract violations as fatal. `resolve` writes `succeeded`, `failed`, or `dead` with result/error/retry metadata. `run_worker` polls until a shared `stop_event` is set and always finishes an in-flight job before exiting.
- **`axiom-queue/watchdog.py`** — Stall reclaimer. Running jobs whose `claimed_at` is older than `STALL_THRESHOLD_SECONDS = 300.0` are reset to `pending`; `attempts` is preserved, claim metadata is cleared, and a reclaim note is appended to the job body for vault-level auditability. `run_watchdog` scans every `DEFAULT_SCAN_INTERVAL_SECONDS = 10.0` by default.
- **`axiom-queue/dispatcher.py`** — Runnable queue service. Enforces one dispatcher per vault with a pidfile under `$XDG_CACHE_HOME/mono-axiom/axiom-queue.pid` (or `~/.cache/mono-axiom/axiom-queue.pid`), starts worker and watchdog loops, installs SIGINT/SIGTERM handlers in the CLI, and shuts down cleanly through a shared `threading.Event`. Runs as `python -m axiom_queue.dispatcher --host 127.0.0.1 --port 7070`; editable installs also expose `axiom-queue`.

#### axiom-fetch

- **`axiom-fetch/ids.py`** — `new_source_id()` returns `src-<12 hex chars>`, `chunk_id_for(source_id, index)` returns deterministic chunk IDs like `src-abc123def456-0007`, and `now_iso()` matches the vault-wide UTC `YYYY-MM-DDTHH:MM:SSZ` timestamp convention.
- **`axiom-fetch/fetcher.py`** — Network boundary for the layer. `fetch(url, timeout=30.0, max_bytes=20 MB, client=None)` uses `httpx`, follows redirects, sends the project user agent, and returns a `FetchResult`. Network, timeout, HTTP 4xx/5xx, and size-cap failures become `status="failed"` results; only programmer errors raise.
- **`axiom-fetch/extractor.py`** — Pure extraction boundary. Supports `text/html` via BeautifulSoup + markdownify and `text/plain` as decoded Markdown passthrough. HTML extraction strips chrome tags (`script`, `style`, `nav`, `header`, `footer`, `aside`, `noscript`), chooses main content by `<main>`, `<article>`, `[role=main]`, `<body>`, then normalizes whitespace. PDF and DOCX intentionally raise `UnsupportedContentType` for now.
- **`axiom-fetch/chunker.py`** — Pure fixed-character chunker. Defaults: `DEFAULT_CHUNK_SIZE = 2000`, `DEFAULT_OVERLAP = 200`, soft-boundary lookback of 50 characters. Returns frozen `Chunk` records with `text`, `index`, `char_count`, and `overlap_chars`. Token-aware chunking is deferred until provider/model choices in later phases need it.
- **`axiom-fetch/pipeline.py`** — `ingest(url, store, chunk_size=..., overlap=...)` composes fetch, extract, chunk, and vault writes. Source files live under `fetch/sources/`, chunk files under `fetch/chunks/`. It writes the source before work starts (`pending`) so interrupted ingests leave visible intent in the vault; terminal source metadata records `succeeded`/`failed`, content type, title, chunk count, fetched timestamp, or error.

### Surviving Phase 0 artifacts

- `scratch/parse_frontmatter.py` — B1 (superseded by `axiom-store/frontmatter.py`; retained as Phase 0 exercise reference)
- `scratch/echo_server.py` + `scratch/echo_client.py` — B2 (superseded conceptually by `axiom-store/server.py` and `axiom-store/client.py`; retained because they're where the framing problem was felt empirically before being solved deliberately)

---

## What's confirmed in place

**Repository**

- `git@github.com:disposably-mono/mono-AXIOM.git` — public, Apache 2.0, branch `main`
- Cloned locally at `/home/mono/Projects/mono-axiom/`

**Scaffold (committed and pushed)**

- Five layer packages — `axiom-store`, `axiom-queue`, `axiom-fetch`, `axiom-brain`, `axiom-api` — each with `__init__.py` and `README.md` (the first three now have real implementation surfaces)
- `pyproject.toml` — workspace config, hyphen filesystem names mapped to underscore Python import names via explicit `[tool.setuptools] packages` + `package-dir` (auto-discovery via `find` does not work with the flat per-layer layout). Runtime deps: `PyYAML>=6.0`, `httpx>=0.27`, `beautifulsoup4>=4.12`, `markdownify>=0.11`. `testpaths` enumerates per-layer `tests/` directories.
- `.gitignore` — covers Python, secrets (`mono-vault/`, `.env`), editor and OS artifacts
- `.env.example` — placeholders for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `VAULT_PATH`, `STORE_PORT`, `API_PORT`. The example `VAULT_PATH` is anchored to `/home/mono/Projects/mono-axiom/mono-vault`.
- `LICENSE` — Apache 2.0
- `README.md` — project overview and layer table
- `scripts/bootstrap_vault.py` — idempotent, copies `mono-vault.example/` to real vault location
- `scripts/demo_axiom_store.py` — end-to-end store demo against a live server
- `scripts/demo_axiom_queue.py` — end-to-end queue demo against a live store server and running dispatcher

**Vault skeleton (`mono-vault.example/`, committed)**

- Full directory structure per PRD §4
- Per-folder `README.md` with documented frontmatter schemas for every content type
- `system/` designated for plain Markdown system docs (no frontmatter)

**Vault (local, gitignored)**

- `mono-vault/` bootstrapped at `/home/mono/Projects/mono-axiom/mono-vault/`
- `mono-vault/system/PRD.md` and `mono-vault/system/Documentation.md` copied in manually

**Scratch directory**

- `scratch/parse_frontmatter.py`, `scratch/echo_server.py`, `scratch/echo_client.py` — Phase 0 exercise references

**`axiom-store` package (complete)**

- `axiom-store/__init__.py` — re-exports the public surface. Phase 2 additions: schema instances (`CONVERSATION`, `FACT`, `FETCH_CHUNK`, `FETCH_SOURCE`, `JOB`, `PERSONA`, `SUMMARY`) and the test-utility surface stay in `axiom_store.test_utils` rather than `__init__`.
- `axiom-store/frontmatter.py` — frontmatter parse/render
- `axiom-store/filesystem.py` — `VaultFS` class, path discipline, all disk I/O for the vault
- `axiom-store/cache.py` — `CachedVaultStore` write-through cache
- `axiom-store/schema.py` — per-content-type schema definitions and `validate`. `JOB` schema rewritten in Phase 2; `FETCH_SOURCE` and `FETCH_CHUNK` schemas rewritten in Phase 3.
- `axiom-store/protocol.py` — hybrid framing (parse/format, pure functions)
- `axiom-store/server.py` — accept loop, `recv_until` + `recv_exact`, `dispatch`, CLI entry point
- `axiom-store/client.py` — `StoreClient` with status-to-exception translation
- `axiom-store/test_utils.py` — `LocalServer`, `send_request`. Public test utility, importable across layers.
- `axiom-store/tests/test_frontmatter.py` — 18 tests
- `axiom-store/tests/test_filesystem.py` — 29 tests
- `axiom-store/tests/test_cache.py` — 16 tests
- `axiom-store/tests/test_schema.py` — 37 tests (12 original + 9 JOB tests pinning the Phase 2 shape + 16 FETCH schema tests pinning the Phase 3 shape and old-shape rejection)
- `axiom-store/tests/test_protocol.py` — 17 tests
- `axiom-store/tests/test_dispatch.py` — 13 tests (pure dispatch, in-memory)
- `axiom-store/tests/test_server.py` — 8 tests (real TCP, real socket, real round trip; now uses `LocalServer` from `axiom_store.test_utils`)
- `axiom-store/tests/test_client.py` — 11 tests (real server + real client + status translation; now uses `LocalServer` from `axiom_store.test_utils`)
- **Total: 155 passing.** (Phase 1: 130 → 139 after JOB schema migration tests → 155 after FETCH_SOURCE/FETCH_CHUNK migration tests.)

**`axiom-queue` package (runnable service complete)**

- `axiom-queue/__init__.py` — re-exports the public queue surface across jobs, handlers, retry, worker, watchdog, and dispatcher.
- `axiom-queue/ids.py` — UUID4 + ISO 8601 helpers
- `axiom-queue/jobs.py` — `Job` dataclass, frontmatter roundtrip, `StoreClient` I/O, `create_pending_job` factory
- `axiom-queue/handlers.py` — registry + `echo` and `noop` starter handlers + `dispatch`
- `axiom-queue/retry.py` — `compute_backoff`, `RetryDecision`, `decide_after_*`, `is_ready_to_retry`
- `axiom-queue/worker.py` — scan/claim/execute/resolve loop
- `axiom-queue/watchdog.py` — stalled-running-job detection and reclaim
- `axiom-queue/dispatcher.py` — queue-service lifecycle, pidfile guard, CLI
- `axiom-queue/tests/test_jobs.py` — 23 tests
- `axiom-queue/tests/test_retry.py` — 29 tests
- `axiom-queue/tests/test_handlers.py` — 20 tests
- `axiom-queue/tests/test_worker.py` — 31 tests
- `axiom-queue/tests/test_watchdog.py` — 32 tests
- `axiom-queue/tests/test_dispatcher.py` — 10 tests
- **Total: 146 passing.**

**`axiom-fetch` package (URL ingestion MVP complete)**

- `axiom-fetch/__init__.py` — re-exports the public fetcher, extractor, chunker, ID, and pipeline surface.
- `axiom-fetch/ids.py` — source IDs, chunk IDs, UTC timestamps.
- `axiom-fetch/fetcher.py` — HTTP GET via `httpx`, redirect-aware, failure-as-data, response size cap.
- `axiom-fetch/extractor.py` — HTML/plain-text to Markdown extraction.
- `axiom-fetch/chunker.py` — overlapping fixed-character chunks with soft boundary handling.
- `axiom-fetch/pipeline.py` — `ingest()` orchestration and vault persistence to `fetch/sources/` and `fetch/chunks/`.
- `axiom-fetch/tests/test_ids.py`
- `axiom-fetch/tests/test_fetcher.py`
- `axiom-fetch/tests/test_extractor.py`
- `axiom-fetch/tests/test_chunker.py`
- `axiom-fetch/tests/test_pipeline.py`
- **Total: 119 passing.**

**Repo-wide test count: 420 passing.**

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
- **Scaffold README is not a job.** `jobs/README.md` ships with the vault skeleton and is intentionally ignored by `list_jobs`; only real job files are returned to worker/watchdog scans.
- **Lexicographic timestamp comparison.** `is_ready_to_retry` compares ISO 8601 strings directly. Safe because the format is fixed-width UTC with `Z`. Regression-pinned.
- **Worker claim increments attempts before execution.** If a worker crashes mid-handler, the vault already records that an attempt started; the watchdog does not grant a free retry.
- **Fatal failures skip retry.** Unknown job kinds and handler contract violations go directly to `dead`; ordinary handler exceptions use the retry policy.
- **Watchdog reclaim is `running -> pending`, not `failed`.** A stall is a worker-lifecycle problem, not downstream flakiness. `attempts` is preserved and claim metadata is cleared.
- **Dispatcher concurrency boundary.** Phase 2 runs one dispatcher process per vault, with one worker loop and one watchdog loop. The pidfile prevents accidentally starting two queue services against the same vault. Multi-worker claiming is deferred until the store has an atomic claim primitive.
- **Public surface widening in `axiom_store`:** schema instances (`JOB`, `FACT`, `SUMMARY`, `CONVERSATION`, `PERSONA`, `FETCH_SOURCE`, `FETCH_CHUNK`) re-exported. Sets the rule that schema instances are public for all consumers, not just `axiom-queue`.
- **`LocalServer` and `send_request` promoted** from `axiom-store/tests/test_server.py` (where they were file-private) into `axiom_store.test_utils`. Public, importable, single source of truth for live-server tests across all layers.
- **Rootless test layout adopted.** No `__init__.py` in `axiom-store/tests/` or `axiom-queue/tests/`. Avoids the `tests.*` namespace collision pytest creates when multiple package-shaped test directories exist in one repo. Phase 3, 4, 5 test directories also won't have `__init__.py`.

**Decisions locked (Phase 3 — fetch ingestion MVP)**

- **FETCH_SOURCE schema:** required keys are `id`, `type`, `status`, `url`, `created_at`, `updated_at`. Optional keys are `fetched_at`, `content_type`, `title`, `error`, `chunk_count`, `tags`. The old placeholder shape (`type`, `url`, `fetched_at`) is rejected.
- **FETCH_CHUNK schema:** required keys are `id`, `type`, `source_id`, `chunk_index`, `chunk_total`, `created_at`, `char_count`. Optional keys are `overlap_chars`, `tags`. The old `source` field and `embedding_path` are rejected; embedding metadata belongs to later retrieval/index work.
- **Source ID shape:** `src-<12 hex chars>`. Short enough for human inspection, enough entropy for a personal vault.
- **Chunk ID shape:** `<source_id>-<index:04d>`. Chunk IDs are deterministic and naturally filename-sortable.
- **HTTP boundary:** `fetcher.py` is the only module that performs network I/O. Tests inject `httpx.MockTransport` or monkeypatch the pipeline fetch call; no unit test calls the public internet.
- **Failure model:** fetch and extraction failures are persisted as failed source metadata, not raised through `ingest()`. Programmer errors (`bad URL`, invalid chunk parameters, invalid body type) still raise.
- **Supported extraction formats:** HTML and plain text only. PDF and DOCX remain deferred even though the PRD calls for them in Phase 3.
- **HTML extraction heuristic:** strip chrome tags everywhere, then select main content by `<main>`, `<article>`, `[role=main]`, `<body>`, then whole document fallback.
- **Chunking unit:** characters, not tokens. Defaults are 2000 characters with 200-character overlap. Token-aware chunking is deferred until provider-specific retrieval quality requires it.
- **Two-phase source write:** `ingest()` writes a pending source before fetching and overwrites it with terminal `succeeded`/`failed` metadata later. A crash mid-ingest leaves visible intent in the vault.

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

**Status:** complete for the intentionally single-dispatcher milestone. True multi-worker process pooling is deferred until the store has an atomic claim primitive.

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
- `worker.py` — claim/execute/resolve loop with retry integration.
- `watchdog.py` — stalled running-job reclaim.
- `dispatcher.py` — pidfile-guarded service lifecycle and CLI entry point.
- `scripts/demo_axiom_queue.py` — human-facing queue demo that prints the absolute job path in the intended uppercase `Projects` repo.
- JOB schema migrated to the Phase 2 shape.
- `axiom_store.test_utils` extracted and adopted by both Phase 1 and Phase 2 tests.

**Checklist items unblocked:**

- [x] Concept understood: GIL and why multiprocessing over threading for CPU work
- [x] Concept understood: IPC between main process and workers (vault-as-IPC, walked but not yet implemented)
- [x] Concept understood: idempotency and why it matters for retries
- [x] Implement job file creation in `mono-vault/jobs/` (via `create_pending_job` + `write_job`)
- [x] Implement worker loop/service
- [x] Implement job pickup (worker reads pending/ready failed job files)
- [x] Implement retry logic with exponential backoff
- [x] Implement job status updates (written back to vault via `axiom-store`)
- [x] Implement watchdog reclaim for stalled running jobs
- [x] Implement dispatcher CLI entry point and pidfile guard
- [x] Implement human-facing queue demo script
- [x] Milestone path confirmed in tests: submit a job, dispatcher/worker executes, result lands in vault

---

## Phase 3 progress

**Status:** URL ingestion MVP complete; broader retrieval layer still in progress.

**Concepts walked:**

- **Failure as vault state.** Fetch and extractor failures are recorded in `FETCH_SOURCE` frontmatter so operators can inspect what happened without searching logs.
- **Network boundary discipline.** `fetcher.py` owns HTTP and returns structured results; extractor/chunker/pipeline logic is deterministic and testable without network access.
- **Main-content extraction.** HTML conversion now strips site chrome, picks the most semantically meaningful content element available, and converts to Markdown with a small dependency rather than handwritten HTML parsing.
- **Character chunking tradeoff.** Characters are deterministic and provider-independent; token-aware chunking remains a quality upgrade for later.
- **Two-phase ingest.** Pending source write first, terminal update last, so interrupted work leaves an auditable marker in the vault.

**Implementation done:**

- `ids.py` — source/chunk ID and timestamp helpers.
- `fetcher.py` — HTTP GET with redirect support, user agent, timeout, size cap, and failure-as-data result shape.
- `extractor.py` — HTML and plain-text extraction to Markdown.
- `chunker.py` — overlapping character chunking with soft boundary handling.
- `pipeline.py` — `ingest()` writes source and chunk Markdown files through an injected store.
- FETCH schemas migrated in `axiom-store/schema.py`.
- Phase 3 tests added for schema, IDs, fetcher, extractor, chunker, and pipeline.

**Checklist items unblocked:**

- [x] Implement HTTP fetch boundary
- [x] Implement HTML extraction to Markdown
- [x] Implement plain-text extraction
- [x] Implement chunking with overlap
- [x] Implement source and chunk persistence to vault
- [x] Milestone path confirmed in tests: URL ingestion produces source and chunk files in the vault

## What's documented but not yet implemented

Everything in the PRD beyond the current URL-ingestion slice of `axiom-fetch`: uploads, PDF/DOCX extraction, retrieval search/indexing, embeddings, `axiom-brain`, and `axiom-api`.

---

## Open questions / deferred decisions

- Frontend framework for `axiom-api` — React vs vanilla JS, deferred to Phase 5
- Embedding model and vector index strategy for `axiom-fetch` — still deferred; current Phase 3 work persists chunks but does not embed or search them yet
- `scripts/sync_vault_docs.py` — copy PRD + Documentation into `mono-vault/system/` on demand. Still manual for now.
- Manual vault edits invalidate the in-memory cache. Phase 1 ships with "restart `axiom-store` after manual edits" as the documented workaround. Upgrade to mtime-check on read in Phase 2 or 3 if it becomes annoying in practice — `test_known_limitation_out_of_band_edit_returns_stale` is pinned to fail when the upgrade lands
- Atomic writes (write-temp + fsync + rename) are deferred. Single-writer assumption holds for now. Revisit when concurrent readers or crash-safety become real concerns
- Persistent-connection upgrade for the client. One-shot is simple and works; if loopback overhead ever shows up in profiling, the upgrade path is documented (server-side connection loop, client-side connection pool). Not a Phase 2 concern
- Per-job `timeout` field on jobs. Phase 2 ships with a fixed 5-minute stall threshold. When a job kind needs a different bound (long PDF chunking, slow LLM calls), promote the timeout into the JOB schema as an optional field.
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
