# Mono-AXIOM — Documentation

The running source of truth for what is actually built and working. Updated incrementally after each feature is confirmed functional.

For the architectural plan and full checklist, see `PRD.md`.

---

## Current state

**Phase:** 0 — Foundations
**Active work:** Concept track complete; one of two Phase 0 exercises complete. Next: TCP echo server exercise (B2), then Phase 1 — `axiom-store`.

---

## Layer status

| Layer | Status | Notes |
|---|---|---|
| `axiom-store` | Stubbed | Package exists, no implementation. `parse_frontmatter` written in `scratch/` as Phase 0 exercise — will be ported in clean when Phase 1 starts. |
| `axiom-queue` | Stubbed | Package exists, no implementation |
| `axiom-fetch` | Stubbed | Package exists, no implementation |
| `axiom-brain` | Stubbed | Package exists, no implementation |
| `axiom-api` | Stubbed | Package exists, no implementation |

---

## What works end to end

Nothing yet at the system level. One isolated component:

- `scratch/parse_frontmatter.py` — splits a Markdown file into `(metadata: dict, body: str)`. Passes all 7 spec cases: standard frontmatter, no frontmatter, empty frontmatter block, frontmatter with no body, malformed (raises `ValueError`), empty file, and mid-document `---` (correctly not treated as frontmatter). Uses `pyyaml`'s `safe_load`; fence detection and slicing written from scratch.

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
- Phase 0 exercises live in `scratch/`; clean implementations enter the layer packages in their respective phases

---

## Phase 0 progress

**Concept track — complete (by walkthrough, not by external reading):**
- TCP fundamentals — layered model, why TCP over UDP, what TCP guarantees and doesn't, byte-stream vs message-stream
- Sockets API — `socket`/`bind`/`listen`/`accept`/`connect`/`recv`/`sendall`, listener vs client sockets, blocking semantics, `bytes` vs `str`
- The framing problem — short reads, coalesced messages, split boundaries; delimiter framing, length-prefix framing, hybrid framing; `recv_exact` pattern
- YAML frontmatter — fence detection, `yaml.safe_load`, splitting parsing from validation, `safe_load` vs `load`
- Write-through caching — write-through vs write-back vs write-around, the cache invariant, why `axiom-store` doesn't need a lock (single-process, TCP-serialized writes)

**Exercises:**
- B1 — `parse_frontmatter`: complete. Lives in `scratch/parse_frontmatter.py`. Will be re-implemented cleanly in `axiom-store/` during Phase 1.
- B2 — TCP echo server + client: not yet started.

**Not yet done (external readings on the Phase 0 checklist):**
- Kurose chapters 1, 2.1–2.4, 3.1–3.4
- Beazley "Python Concurrency from the Ground Up" (PyCon 2015)
- Beej's Guide chapters 1–5
- Python `socket`, `asyncio`, `multiprocessing` docs
- YAML 1.2 spec + `pyyaml` docs

These will reinforce and deepen what's been covered in the walkthroughs. They are not blockers for B2 or for Phase 1.

---

## What's documented but not yet implemented

Everything in the PRD beyond Phase 0 scaffolding and `parse_frontmatter`.

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
