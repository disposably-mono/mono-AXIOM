# Mono-AXIOM
### A Personal AI Intelligence Stack — Product Requirements Document

**Author:** Mono (Mikel Taopa)
**Version:** 1.2
**Status:** Active
**Last Updated:** May 21, 2026
**Target Completion Window:** ~90 days (pre-ADMU, August 2026)

---

## 1. Vision

Mono-AXIOM is a personal AI infrastructure stack built layer by layer, from scratch, in Python. Rather than wrapping a framework like LangChain or LlamaIndex, every component is built and owned end to end — storage, scheduling, retrieval, inference, and exposure.

The name **AXIOM** reflects the project philosophy: build from self-evident foundations. Each layer is a primitive truth the next layer depends on.

The end state is a unified system accessible through a web dashboard, capable of routing tasks between Claude, GPT, and a local model, with a fully human-readable Markdown-based memory that is Obsidian-compatible.

---

## 2. Project Philosophy

- **Build from scratch.** No framework hides the internals.
- **Concept-first.** Understand each layer before writing code.
- **Composable.** Each layer is a working component, usable in isolation.
- **Transparent.** Memory and state are readable, editable, and inspectable as `.md` files.
- **One system.** Every project feeds into the next — not five separate portfolio pieces.

---

## 3. The Five Layers

| Layer | Codename | Role |
|---|---|---|
| 1 | `axiom-store` | Persistent state layer — Markdown-backed file system store |
| 2 | `axiom-queue` | Job dispatch, worker management, retry logic |
| 3 | `axiom-fetch` | Web retrieval, document ingestion, RAG chunking |
| 4 | `axiom-brain` | Multi-provider inference, intent routing, tool calls, memory management |
| 5 | `axiom-api` | Unified HTTP gateway + web dashboard |

---

## 4. Vault Architecture

All persistent state lives in a single directory: `/mono-vault/`. Every file is human-readable Markdown with YAML frontmatter for metadata. System-level reference documents (`PRD.md`, `Documentation.md`) live in `system/` as plain Markdown without frontmatter.

```
mono-vault/
├── memory/
│   ├── conversations/
│   ├── facts/
│   └── summaries/
├── personas/
├── fetch/
│   ├── sources/
│   ├── chunks/
│   └── uploads/
├── jobs/
├── system/
│   ├── PRD.md
│   └── Documentation.md
└── exports/
```

The vault is the single source of truth for all persistent state. No layer is permitted to store durable state outside it.

---

## 5. Layer Details

### 5.1 `axiom-store`

A TCP-accessible Markdown store with a write-through cache.

- Sockets-based interface (no HTTP, no framework — direct TCP)
- Validates YAML frontmatter against per-type schemas
- In-memory cache for hot reads
- Filesystem is the durable backing store
- Other layers connect over TCP, never touch the filesystem directly

**Concepts learned:** TCP sockets, framing protocols, file I/O, Markdown/YAML parsing, write-through caching.

**Milestone:** Other layers can read/write vault entries via a TCP client without touching the filesystem.

### 5.2 `axiom-queue`

A job dispatch system with worker processes and retry logic.

- Jobs are submitted as `.md` files in `/mono-vault/jobs/`
- Worker processes pick up pending jobs, execute, write results back
- Retries with exponential backoff on failure
- Status visible by reading the job file

**Concepts learned:** Concurrency (GIL implications), `multiprocessing`, IPC, retry strategies, idempotency.

**Milestone:** Submit a job, see it executed by a worker, see the result land in the vault.

### 5.3 `axiom-fetch`

A retrieval and ingestion pipeline.

- Web fetch via `httpx`, parse HTML to Markdown
- PDF and `.docx` extraction
- Chunking with configurable size and overlap
- All output lands in `/mono-vault/fetch/`

**Concepts learned:** HTTP semantics, HTML parsing, document formats, chunking strategies, RAG fundamentals.

**Milestone:** Given a URL or uploaded file, produce retrievable chunks in the vault.

### 5.4 `axiom-brain`

Multi-provider inference with intent routing and tool calls.

- Provider abstraction: Anthropic Claude, OpenAI GPT, local Ollama (Qwen3 4B)
- Intent classifier routes each turn to the best provider
- Tool-calling loop: inference → parse → execute → re-inject
- Memory commands: read/write/summarize via `axiom-store`
- Context overflow handled by rolling summaries

**Concepts learned:** Provider API patterns, tool-use protocols, the inference loop, prompt engineering, context management.

**Milestone:** A single turn can route to any provider, call a tool, write a fact, and return a coherent response.

### 5.5 `axiom-api`

A FastAPI gateway and web dashboard.

#### 5.5.1 Chat
Streaming chat UI backed by `axiom-brain`. Server-sent events for token streaming.

#### 5.5.2 Memory browser
Browse and edit `/mono-vault/memory/`. Changes are saved through `axiom-store`.

#### 5.5.3 RAG upload
Drop files; they get chunked into `fetch/chunks/` and become immediately retrievable.

#### 5.5.4 Job monitoring
Live view of `/mono-vault/jobs/` — pending, running, succeeded, failed.

#### 5.5.5 Settings
Provider keys, routing rules, model selection, vault path. Persisted in `system/`.

#### 5.5.6 Upload
Supported formats: PDF, `.md`, `.txt`, `.docx`. Uploaded files are stored in `/mono-vault/fetch/uploads/`, chunked by the same pipeline as fetched web pages, and become immediately available for RAG. The retrieval system does not distinguish between web-fetched and uploaded sources — both are just `.md` chunks in the vault.

#### 5.5.7 Export
Three export modes:
- **Conversation export** — single `.md` file of the full session, appended to `/mono-vault/memory/conversations/` and downloadable
- **Vault export** — complete `.zip` snapshot of `/mono-vault/`
- **Session export** — current active context window as a formatted `.md` report

All exports are Obsidian-compatible by default.

**Concepts learned:** REST API design, HTTP semantics, FastAPI patterns, middleware, request validation, server-sent events, streaming responses, frontend integration, observability.

**Milestone:** A running local web app where the user can chat with provider routing, browse and edit memory files, upload documents to RAG, monitor jobs, configure the system, and export — all without touching the terminal.

---

## 6. Local Model Configuration

**Target hardware:** Lenovo IdeaPad Gaming 3 — i5-11320H, 16GB RAM, RTX 3050 Ti Mobile (4GB VRAM), Fedora 44.

**Selected model:** Qwen3 4B (Q4_K_M quantization) via Ollama.

Rationale: Fits fully in 4GB VRAM with headroom for context. Supports tool calling natively. Strong reasoning scores for its size (74% MMLU-Pro). Used for fast offline tasks, intent classification, summarization, and privacy-sensitive queries. Not a replacement for Claude or GPT — a complement that handles work where API latency and cost don't make sense.

---

## 7. Tech Stack

| Component | Choice | Reasoning |
|---|---|---|
| Language | Python 3.14 | User comfort, fast iteration |
| Packaging | `setuptools` + `pyproject.toml`, editable install | Standard library tooling. Hyphen-folder layout (e.g. `axiom-store/`) mapped to underscore Python imports (`axiom_store`) via explicit `[tool.setuptools] packages` + `package-dir`. Auto-discovery (`find`) does not work with the flat per-layer layout. |
| YAML parsing | `PyYAML>=6.0` (`safe_load`, `safe_dump`) | First and only runtime dependency in Phase 1. Required for frontmatter. `safe_load` rejects arbitrary Python object construction. |
| API framework | FastAPI | Modern, async-native, streaming support (Phase 5) |
| Local inference | Ollama + Qwen3 4B | Fits hardware, tool-use capable (Phase 4) |
| Storage format | Markdown + YAML frontmatter | Human-readable, Obsidian-compatible |
| Concurrency | Python `asyncio` + worker processes | Standard library, no extra deps. `axiom-store` itself is single-threaded one-shot TCP — concurrency arrives in Phase 2 with `axiom-queue` workers. |
| Frontend | React or vanilla JS (TBD in Phase 5) | User has JS comfort, React optional |
| Editor environment | Neovim + VS Code on Fedora 44 | User's confirmed setup |
| Testing | `pytest>=8.0` (dev dependency) | Per-layer `tests/` directories enumerated in `[tool.pytest.ini_options] testpaths`. |
| Linting | `ruff>=0.5`, `mypy>=1.10` (dev dependencies) | Strict but light-weight. |

---

## 8. Phased Build Timeline

| Phase | Weeks | Focus | Status |
|---|---|---|---|
| 0. Foundations | 1–2 | Networking basics, socket programming, Markdown/YAML parsing, project scaffolding | Complete |
| 1. `axiom-store` | 3–5 | Markdown-backed store with TCP interface and write-through cache | **Complete** |
| 2. `axiom-queue` | 6–8 | Job system, workers, retries | Next |
| 3. `axiom-fetch` | 9–11 | Retrieval and chunking pipeline | Pending |
| 4. `axiom-brain` | 12–15 | Provider abstraction, intent routing, tool-calling loop, memory commands | Pending |
| 5. `axiom-api` | 16–18 | FastAPI gateway, web dashboard, streaming, settings UI, exports | Pending |

Each phase ends with its milestone being demonstrably working before moving on. If timing slips, layers 4 and 5 are scoped down — but never skipped.

---

## 9. Project Checklist

Progress tracker across all phases. Check off items as they are confirmed working.

### Phase 0 — Foundations

- [x] Project named and philosophy finalized
- [x] Repository created (`disposably-mono/mono-AXIOM`, public, Apache 2.0)
- [x] Full scaffold committed — five layer stubs, `pyproject.toml`, `.gitignore`, `.env.example`, `LICENSE`
- [x] Vault skeleton committed (`mono-vault.example/`) with documented frontmatter schemas
- [x] `bootstrap_vault.py` working and verified
- [x] `PRD.md` and `Documentation.md` in repo and in `mono-vault/system/`
- [ ] Read Kurose Ch. 1 — Computer Networks and the Internet
- [ ] Read Kurose Ch. 2.1–2.4 — Application layer, HTTP, sockets intro
- [ ] Read Kurose Ch. 3.1–3.4 — Transport layer, TCP basics
- [ ] Watch Beazley "Python Concurrency from the Ground Up" (PyCon 2015)
- [ ] Read Beej's Guide Ch. 1–5
- [ ] Read Python `socket` module docs
- [ ] Read Python `asyncio` — Coroutines and Tasks (first two sections)
- [ ] Read Python `multiprocessing` docs — Introduction
- [ ] Read YAML 1.2 spec Ch. 1 + `pyyaml` docs
- [x] Exercise: write `parse_frontmatter(path) -> tuple[dict, str]` from scratch
- [x] Exercise: write a toy TCP echo server in Python using raw `socket`

External readings remain on the list but are no longer Phase 2 blockers — the concepts have been encountered in practice during Phase 1. Reading them remains valuable for reinforcement.

### Phase 1 — `axiom-store`

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

**Phase 1 complete.** Hybrid `\n`-delimited header + length-prefixed body protocol. One-shot connections. Write-through cache over a path-disciplined `VaultFS`. `StoreClient` substitutable for `CachedVaultStore` from any caller's perspective. 130 tests passing. End-to-end demo in `scripts/demo_axiom_store.py`.

### Phase 2 — `axiom-queue`

- [x] Concept understood: GIL and why multiprocessing over threading for CPU work
- [x] Concept understood: IPC between main process and workers
- [x] Concept understood: idempotency and why it matters for retries
- [x] Implement job file creation in `mono-vault/jobs/`
- [ ] Implement worker process pool
- [x] Implement job pickup (worker reads pending job files)
- [x] Implement retry logic with exponential backoff
- [x] Implement job status updates (written back to vault via `axiom-store`)
- [x] Implement watchdog reclaim for stalled running jobs
- [x] Implement dispatcher CLI entry point and pidfile guard
- [x] Implement queue demo script
- [x] Milestone confirmed: submit a job, worker executes, result lands in vault

Phase 2 currently ships one pidfile-guarded dispatcher service with one worker loop and one watchdog loop. True multi-worker pooling remains deferred until the store has an atomic claim primitive. The local demo path is anchored to `/home/mono/Projects/mono-axiom/mono-vault`.

### Phase 3 — `axiom-fetch`

- [ ] Concept understood: HTTP request/response cycle
- [ ] Concept understood: HTML parsing and content extraction
- [ ] Concept understood: chunking strategies and overlap for RAG
- [ ] Implement web fetch via `httpx`
- [ ] Implement HTML → Markdown conversion
- [ ] Implement PDF ingestion
- [ ] Implement `.docx` ingestion
- [ ] Implement chunker (configurable size + overlap)
- [ ] Implement source and chunk persistence to vault
- [ ] Milestone confirmed: URL or uploaded file produces retrievable chunks in vault

### Phase 4 — `axiom-brain`

- [ ] Concept understood: provider API patterns (Anthropic, OpenAI, Ollama)
- [ ] Concept understood: tool-calling loop (inference → parse → execute → re-inject)
- [ ] Concept understood: context window management and overflow
- [ ] Implement provider abstraction base class
- [ ] Implement Anthropic provider
- [ ] Implement OpenAI provider
- [ ] Implement Ollama provider (Qwen3 4B)
- [ ] Implement intent classifier and routing rules
- [ ] Implement tool-calling loop
- [ ] Implement memory commands (read, write, summarize via `axiom-store`)
- [ ] Implement context overflow handler (rolling summaries)
- [ ] Milestone confirmed: single turn routes to correct provider, calls a tool, writes a fact, returns coherent response

### Phase 5 — `axiom-api`

- [ ] Concept understood: server-sent events vs WebSockets
- [ ] Concept understood: FastAPI middleware and request lifecycle
- [ ] Implement FastAPI app skeleton and routing
- [ ] Implement `/chat` endpoint with SSE streaming
- [ ] Implement memory browser endpoints (list, read, write)
- [ ] Implement RAG upload endpoint
- [ ] Implement job monitoring endpoints
- [ ] Implement settings endpoints (provider keys, routing, vault path)
- [ ] Implement export endpoints (conversation, vault zip, session)
- [ ] Implement frontend (React or vanilla JS — TBD)
- [ ] Milestone confirmed: full web app running locally without terminal access

---

## 10. Success Criteria

By August 2026, Mono-AXIOM is considered complete when:

1. All five layers run together as a single integrated system.
2. The vault is a fully usable Obsidian vault.
3. The web dashboard supports chat, memory browsing, RAG upload, job monitoring, settings, and export — all without terminal access after initial setup.
4. The system routes between Claude, GPT, and Qwen3 4B automatically based on intent.
5. The tool-calling loop works end to end — model can fetch URLs, search the vault, write to memory, and dispatch jobs.
6. Context overflow is handled transparently via summarization.
7. The project is documented well enough for someone else to clone, configure, and run.

---

## 11. What This Portfolio Demonstrates

To a reader of this codebase, Mono-AXIOM shows:

- Systems thinking — five components designed to compose, not five disconnected projects.
- Infrastructure literacy — storage, scheduling, networking, all built from the ground up.
- AI engineering depth — orchestration, RAG, tool use, multi-provider routing, all implemented without a framework.
- Product sensibility — the system is presentable, configurable, and usable by a human, not just a developer.
- Design philosophy — a transparent, human-readable memory architecture is a deliberate choice, not an accident.

This is not five tutorials stitched together. It is one system, with a thesis behind it.

---

*End of document.*
