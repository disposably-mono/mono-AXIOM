# Mono-AXIOM — Documentation

The running source of truth for what is actually built and working. Updated incrementally after each feature is confirmed functional.

For the architectural plan and full checklist, see `PRD.md`.

---

## Current state

**Phase:** 1 — `axiom-store`: **complete**
**Active work:** None. Ready to begin Phase 2 — `axiom-queue`.

---

## Layer status

| Layer | Status | Notes |
|---|---|---|
| `axiom-store` | Complete | TCP-accessible Markdown store with write-through cache, hybrid framing, schema validation, and a matching client. 130 tests passing. End-to-end demo script runs clean against a live server. |
| `axiom-queue` | Stubbed | Package exists, no implementation |
| `axiom-fetch` | Stubbed | Package exists, no implementation |
| `axiom-brain` | Stubbed | Package exists, no implementation |
| `axiom-api` | Stubbed | Package exists, no implementation |

---

## What works end to end

A complete vault store accessible over TCP from any client. Run the server, point any process at it, and read/write/delete/list Markdown files in the vault. Every byte is validated, every write goes through schema checks, every repeated read is served from cache. The vault stays a fully Obsidian-compatible Markdown directory on disk.

**The live demo** (`scripts/demo_axiom_store.py`) walks the seven verbs and assertions against a running server: WRITE with schema validation, READ roundtrip, LIST, SCHEMA_ERROR rejection, path-traversal rejection (BAD_REQUEST), NOT_FOUND, DELETE, and read-after-delete. All pass.

### Components

- **`axiom-store/frontmatter.py`** — `parse_frontmatter(text) -> (dict, str)` and `render_frontmatter(metadata, body) -> str`. Pure string transforms. `FrontmatterError` (subclass of `ValueError`) on malformed YAML, unclosed fences, or non-mapping YAML. Roundtrip property `parse(render(m, b)) == (m, b)` holds for all tested cases.
- **`axiom-store/filesystem.py`** — `VaultFS` class wrapping a configured vault root. `read`, `write`, `delete`, `list_dir`. Vault-relative paths only; `_resolve` rejects empty/absolute/null-byte/backslash/non-string paths and any path resolving outside the root via `Path.resolve()` + `is_relative_to(root)`. Writes auto-create parent directories. `list_dir` returns sorted filenames, files only. Direct `write_bytes` (atomic-rename deferred per single-writer assumption).
- **`axiom-store/cache.py`** — `CachedVaultStore` wraps a `VaultFS` with `dict[str, bytes]`. Read hit returns from memory; miss reads from disk and populates. Write goes to disk first, then updates the cache. Delete evicts. `list_dir` passes through (not cached). Observable hit/miss counters via `store.stats`. Out-of-band edits not detected (documented Phase 1 limitation, regression-pinned).
- **`axiom-store/schema.py`** — Per-content-type schemas (`FACT`, `SUMMARY`, `CONVERSATION`, `PERSONA`, `JOB`, `FETCH_SOURCE`, `FETCH_CHUNK`) with required/optional keys typed by Python `type`. Longest-prefix registry lookup via `schema_for(vault_path)`. `validate(metadata, schema)` raises `SchemaError` on missing required keys, type mismatches, or unknown keys (unless `allow_extra=True`). Free-form areas (`system/`, `exports/`, `fetch/uploads/`) deliberately have no schema and pass through unvalidated.
- **`axiom-store/protocol.py`** — Hybrid framing on the wire: `\n`-delimited header lines, blank line, length-prefixed body. Pure-function parsers and formatters: `parse_request_headers`, `parse_response_headers`, `format_request`, `format_response`. Headers are case-sensitive lowercase. `content-length: <n>` is required. `MAX_BODY_BYTES = 10 MB` cap.
- **`axiom-store/server.py`** — `serve_forever(vault_root, host, port)` runs the accept loop. Single-threaded, sequential, one-shot connections. `SO_REUSEADDR` for clean restarts. `recv_until` returns `(before, after)` from header reads so any body bytes coalesced into the same `recv` get prepended to the body read via `recv_exact(initial=after)` — this is the production fix for the framing problem we walked in concept and felt empirically in B2. Pure-function `dispatch(store, request) -> response` translates layer exceptions to protocol statuses (`InvalidVaultPath` → `BAD_REQUEST`, `FileNotFoundError` → `NOT_FOUND`, `SchemaError`/`FrontmatterError` → `SCHEMA_ERROR`, everything else logged → `SERVER_ERROR`). Runs as `python -m axiom_store.server --vault <path>`.
- **`axiom-store/client.py`** — `StoreClient(host, port, timeout)` mirrors `CachedVaultStore`'s interface: `read`, `write`, `delete`, `list_dir`. Connection-per-call (one-shot). Server statuses translate back into Python exceptions matching what the in-process store would raise: `NOT_FOUND` → `FileNotFoundError`, `BAD_REQUEST` → `InvalidVaultPath`, `SCHEMA_ERROR` → `SchemaError`, `SERVER_ERROR` → `StoreError`. **Substitutable** — anywhere a `CachedVaultStore` is acceptable, a `StoreClient` works as a drop-in.
- **`scripts/demo_axiom_store.py`** — Live end-to-end exercise of every verb and every error path against a running server. Bundled so future-you (or anyone reading the repo) can boot the server and watch the stack work in one command.

### Surviving Phase 0 artifacts

- `scratch/parse_frontmatter.py` — B1 (superseded by `axiom-store/frontmatter.py`; retained as Phase 0 exercise reference)
- `scratch/echo_server.py` + `scratch/echo_client.py` — B2 (superseded conceptually by `axiom-store/server.py` and `axiom-store/client.py`; retained because they're where the framing problem was felt empirically before being solved deliberately)

---

## What's confirmed in place

**Repository**
- `git@github.com:disposably-mono/mono-AXIOM.git` — public, Apache 2.0, branch `main`
- Cloned locally at `~/projects/mono-axiom/`

**Scaffold (committed and pushed)**
- Five layer packages — `axiom-store`, `axiom-queue`, `axiom-fetch`, `axiom-brain`, `axiom-api` — each with stub `__init__.py` and `README.md`
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
- `axiom-store/__init__.py` — re-exports `parse_frontmatter`, `render_frontmatter`, `FrontmatterError`, `VaultFS`, `InvalidVaultPath`, `CachedVaultStore`, `Schema`, `SchemaError`, `schema_for`, `validate`, `Request`, `RequestStub`, `Response`, `ResponseStub`, `format_request`, `format_response`, `parse_request_headers`, `parse_response_headers`, `ProtocolError`, `StoreClient`, `StoreError`
- `axiom-store/frontmatter.py` — frontmatter parse/render
- `axiom-store/filesystem.py` — `VaultFS` class, path discipline, all disk I/O for the vault
- `axiom-store/cache.py` — `CachedVaultStore` write-through cache
- `axiom-store/schema.py` — per-content-type schema definitions and `validate`
- `axiom-store/protocol.py` — hybrid framing (parse/format, pure functions)
- `axiom-store/server.py` — accept loop, `recv_until` + `recv_exact`, `dispatch`, CLI entry point
- `axiom-store/client.py` — `StoreClient` with status-to-exception translation
- `axiom-store/tests/__init__.py` — empty (test discovery)
- `axiom-store/tests/test_frontmatter.py` — 18 tests
- `axiom-store/tests/test_filesystem.py` — 29 tests
- `axiom-store/tests/test_cache.py` — 16 tests
- `axiom-store/tests/test_schema.py` — 12 tests
- `axiom-store/tests/test_protocol.py` — 17 tests
- `axiom-store/tests/test_dispatch.py` — 13 tests (pure dispatch, in-memory)
- `axiom-store/tests/test_server.py` — 8 tests (real TCP, real socket, real round trip)
- `axiom-store/tests/test_client.py` — 11 tests (real server + real client + status translation)
- **Total: 130 passing.**

**Decisions locked (across all of Phase 1)**
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

Most of what these would teach has now been encountered in practice during Phase 1. Reading them remains valuable for reinforcement and depth but is no longer on the Phase 2 critical path.

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
- All seven steps complete: frontmatter, filesystem, cache, schema, protocol, server, client. 130 tests passing. Live end-to-end demo working.

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

---

## What's documented but not yet implemented

Everything in the PRD beyond `axiom-store`. Phase 2 (`axiom-queue`) is next.

---

## Open questions / deferred decisions

- Frontend framework for `axiom-api` — React vs vanilla JS, deferred to Phase 5
- Embedding model and vector index strategy for `axiom-fetch` — deferred to Phase 3
- `scripts/sync_vault_docs.py` — copy PRD + Documentation into `mono-vault/system/` on demand. Phase 1 manages this with a one-line `cp`; worth scripting if doc updates become more frequent in Phase 2
- Manual vault edits invalidate the in-memory cache. Phase 1 ships with "restart `axiom-store` after manual edits" as the documented workaround. Upgrade to mtime-check on read in Phase 2 or 3 if it becomes annoying in practice — `test_known_limitation_out_of_band_edit_returns_stale` is pinned to fail when the upgrade lands
- Atomic writes (write-temp + fsync + rename) are deferred. Single-writer assumption holds for now. Revisit when concurrent readers or crash-safety become real concerns
- Persistent-connection upgrade for the client. One-shot is simple and works; if loopback overhead ever shows up in profiling, the upgrade path is documented (server-side connection loop, client-side connection pool). Not a Phase 2 concern

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
