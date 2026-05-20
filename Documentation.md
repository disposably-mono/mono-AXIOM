# Mono-AXIOM — Documentation

The running source of truth for what is actually built and working. Updated incrementally after each feature is confirmed functional.

For the architectural plan, see [`PRD.md`](./PRD.md).

---

## Current state

**Phase:** 0 — Foundations
**Active work:** Project scaffolding and GitHub initialization

## Layer status

| Layer | Status | Notes |
|---|---|---|
| `axiom-store` | Stubbed | Package exists, no implementation |
| `axiom-queue` | Stubbed | Package exists, no implementation |
| `axiom-fetch` | Stubbed | Package exists, no implementation |
| `axiom-brain` | Stubbed | Package exists, no implementation |
| `axiom-api` | Stubbed | Package exists, no implementation |

## What works end to end

Nothing yet. No layer is implemented.

## What's in place

- Git repository initialized: `git@github.com:disposably-mono/mono-AXIOM.git` (public, Apache 2.0)
- Repository scaffold:
  - Five layer packages with stub `__init__.py` and `README.md`
  - `pyproject.toml` with workspace package mapping (hyphen filesystem names → underscore Python imports)
  - `.gitignore` covering Python, secrets, vault, editor, OS artifacts
  - `.env.example` with placeholders for provider keys, Ollama, store/API ports, vault path
  - `LICENSE` (Apache 2.0)
  - `README.md` with project overview and layer table
  - `scripts/bootstrap_vault.py` — copies vault skeleton to real vault location
- Vault skeleton (`mono-vault.example/`):
  - Full directory structure per PRD §4
  - Per-folder `README.md` with documented frontmatter schemas for each content type
- This file (`Documentation.md`) and the PRD copied into the repo

## What's documented but not yet implemented

Everything in the PRD beyond the scaffold itself.

## Open questions / deferred decisions

- Frontend framework choice for `axiom-api` — React vs vanilla JS, deferred to Phase 5
- Embedding model and vector index strategy for `axiom-fetch` — deferred to Phase 3
- Whether to add per-file Apache 2.0 headers — currently no, `LICENSE` only

## Local environment assumptions

- Python 3.14+
- Fedora 44
- Neovim + VS Code
- Ollama installed locally for Phase 4 onward
- RTX 3050 Ti Mobile (4GB VRAM) constrains local model choice to Qwen3 4B Q4_K_M

---

*This file is updated after each feature is confirmed working. Do not pre-document unbuilt work.*
