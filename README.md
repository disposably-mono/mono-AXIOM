# Mono-AXIOM

A personal AI intelligence stack — built from scratch, layer by layer, in Python.

Five composable components form a unified system for orchestrating AI workloads across Claude, GPT, and a local Qwen3 4B model. All persistent state lives in a human-readable Markdown vault, fully editable by hand and compatible with Obsidian.

## Why

Most AI tooling hides its internals behind framework abstractions. Mono-AXIOM is built without LangChain, LlamaIndex, or Celery — every primitive (storage, scheduling, retrieval, inference, exposure) is owned end to end. The point is to understand each layer well enough to have built it.

## The five layers

| Layer | Codename | Role |
|---|---|---|
| 1 | `axiom-store` | Markdown-backed file store with TCP interface |
| 2 | `axiom-queue` | Job dispatch, worker management, retry logic |
| 3 | `axiom-fetch` | Web retrieval, document ingestion, RAG chunking |
| 4 | `axiom-brain` | Multi-provider inference, intent routing, tool calls |
| 5 | `axiom-api` | Unified HTTP gateway + web dashboard |

See [`PRD.md`](./PRD.md) for the full architecture and [`Documentation.md`](./Documentation.md) for the running build state.

## Project status

**Phase 2 — `axiom-queue` in progress.** `axiom-store` is complete, and `axiom-queue` now has job persistence, handlers, retry policy, worker loop, watchdog, and a runnable dispatcher service. Later layers are still stubbed.

## Getting started

> Mono-AXIOM is in active development. These instructions will stabilize once `axiom-store` is functional.

```bash
# 1. Clone
git clone git@github.com:disposably-mono/mono-AXIOM.git
cd mono-AXIOM

# 2. Set up Python environment (3.14+ required)
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 3. Copy environment template and fill in keys
cp .env.example .env
# edit .env

# 4. Bootstrap the vault from the example skeleton
python scripts/bootstrap_vault.py
```

## Repository layout

```
mono-axiom/
├── axiom-store/          ← Layer 1: persistent state
├── axiom-queue/          ← Layer 2: job system
├── axiom-fetch/          ← Layer 3: retrieval
├── axiom-brain/          ← Layer 4: inference orchestration
├── axiom-api/            ← Layer 5: HTTP + dashboard
├── scripts/              ← bootstrap & maintenance utilities
├── tests/                ← per-layer tests
├── mono-vault.example/   ← committed vault skeleton
├── mono-vault/           ← your real vault (gitignored)
├── PRD.md                ← locked product requirements
└── Documentation.md      ← running build state
```

## License

Apache License 2.0 — see [`LICENSE`](./LICENSE).
