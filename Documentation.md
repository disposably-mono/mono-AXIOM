# Mono-AXIOM — Documentation

The running source of truth for what is actually built and working. Updated incrementally after each feature is confirmed functional.

For the architectural plan and full checklist, see `PRD.md`.

---

## Current state

**Phase:** 0 — Foundations
**Active work:** Phase 0 study materials and exercises

---

## Layer status

| Layer | Status | Notes |
|---|---|---|
| `axiom-store` | Stubbed | Package exists, no implementation |
| `axiom-queue` | Stubbed | Package exists, no implementation |
| `axiom-fetch` | Stubbed | Package exists, no implementation |
| `axiom-brain` | Stubbed | Package exists, no implementation |
| `axiom-api` | Stubbed | Package exists, no implementation |

---

## What works end to end

Nothing yet. No layer is implemented.

---

## What's confirmed in place

**Repository**
- `git@github.com:disposably-mono/mono-AXIOM.git` — public, Apache 2.0, branch `main`
- Cloned locally at `~/projects/mono-axiom/`

**Scaffold (committed and pushed)**
- Five layer packages — `axiom-store`, `axiom-queue`, `axiom-fetch`, `axiom-brain`, `axiom-api` — each with stub `__init__.py` and `README.md`
- `pyproject.toml` — workspace config, hyphen filesystem names mapped to underscore Python import names
- `.gitignore` — covers Python, secrets (`mono-vault/`, `.env`), editor and OS artifacts
- `.env.example` — placeholders for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `VAULT_PATH`, `STORE_PORT`, `API_PORT`
- `LICENSE` — Apache 2.0
- `README.md` — project overview and layer table
- `scripts/bootstrap_vault.py` — idempotent, copies `mono-vault.example/` to real vault location

**Vault skeleton (`mono-vault.example/`, committed)**
- Full directory structure per PRD §4
- Per-folder `README.md` with documented frontmatter schemas for every content type
- `system/` designated for plain Markdown system docs (no frontmatter)

**Vault (local, gitignored)**
- `mono-vault/` bootstrapped at `~/projects/mono-axiom/mono-vault/`
- `mono-vault/system/PRD.md` and `mono-vault/system/Documentation.md` copied in manually

**Decisions locked**
- Vault repo strategy: Option B — monorepo, vault gitignored, example skeleton committed
- `system/` docs (`PRD.md`, `Documentation.md`) are plain Markdown, no frontmatter, never queried programmatically
- No `/public` folder — vault is the canonical home for living documents
- No per-file Apache 2.0 headers — `LICENSE` at repo root only

---

## What's documented but not yet implemented

Everything in the PRD beyond Phase 0 scaffolding.

---

## Open questions / deferred decisions

- Frontend framework for `axiom-api` — React vs vanilla JS, deferred to Phase 5
- Embedding model and vector index strategy for `axiom-fetch` — deferred to Phase 3
- `scripts/sync_vault_docs.py` — copy PRD + Documentation into `mono-vault/system/` on demand; to be added when doc updates become regular (end of first completed layer)

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
