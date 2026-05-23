# Handoff

Session date: 2026-05-23

## Summary

This session documents and packages the Phase 3 `axiom-fetch` URL-ingestion MVP.

The working tree now contains:

- `axiom-fetch` implementation for source IDs, HTTP fetch, HTML/plain-text extraction, chunking, and vault persistence.
- `axiom-store` FETCH schema migration for real `FETCH_SOURCE` and `FETCH_CHUNK` frontmatter.
- Runtime dependency updates for `httpx`, `beautifulsoup4`, and `markdownify`.
- Updated docs in `Documentation.md`, `README.md`, this handoff, and `axiom-fetch/README.md`.
- A fresh vault sync of `Documentation.md` to `mono-vault/system/Documentation.md`.

Final commit:

```text
feat(axiom-fetch): add URL ingestion MVP
```

## Starting State

The repository began on `main` with a dirty working tree containing uncommitted Phase 3 code:

- Modified: `axiom-fetch/__init__.py`
- Modified: `axiom-store/schema.py`
- Modified: `axiom-store/tests/test_schema.py`
- Modified: `pyproject.toml`
- Untracked: `axiom-fetch/chunker.py`
- Untracked: `axiom-fetch/extractor.py`
- Untracked: `axiom-fetch/fetcher.py`
- Untracked: `axiom-fetch/ids.py`
- Untracked: `axiom-fetch/pipeline.py`
- Untracked: `axiom-fetch/tests/`

Those changes were treated as current project work and documented instead of reverted.

## Implemented State

### axiom-fetch

`axiom-fetch` is no longer a stub. It now has a tested URL-ingestion path:

- `ids.py` creates `src-<12 hex>` source IDs, deterministic chunk IDs, and UTC `Z` timestamps.
- `fetcher.py` is the network boundary. It uses `httpx`, follows redirects, applies a user agent, enforces a 20 MB response cap, and returns `FetchResult` instead of raising for network/HTTP failures.
- `extractor.py` supports `text/html` and `text/plain`. HTML extraction strips site chrome, selects main content by semantic priority, and converts to Markdown.
- `chunker.py` produces fixed-character chunks with overlap and soft boundary handling.
- `pipeline.py` exposes `ingest(url, store)`, writes a pending source first, then persists chunks and terminal source metadata.
- `__init__.py` re-exports the public surface.

Deferred Phase 3 work:

- Upload ingestion.
- PDF and DOCX extraction.
- Embeddings and retrieval/search.
- Queue-handler integration around `ingest()`.

### axiom-store Schema

`FETCH_SOURCE` now requires:

```text
id, type, status, url, created_at, updated_at
```

Optional:

```text
fetched_at, content_type, title, error, chunk_count, tags
```

`FETCH_CHUNK` now requires:

```text
id, type, source_id, chunk_index, chunk_total, created_at, char_count
```

Optional:

```text
overlap_chars, tags
```

The old placeholder shapes are rejected by tests.

### Dependencies

`pyproject.toml` now includes:

```text
httpx>=0.27
beautifulsoup4>=4.12
markdownify>=0.11
```

## Documentation Updated

Updated:

- `Documentation.md`
- `README.md`
- `Handoff.md`
- `axiom-fetch/README.md`

`Documentation.md` now marks:

- Phase 3 as active.
- `axiom-store` complete with 155 tests.
- `axiom-queue` runnable-service complete with 146 tests.
- `axiom-fetch` URL-ingestion MVP complete with 119 tests.
- Repo-wide test count at 420 passing.

## Vault Sync

Synced:

```text
Documentation.md -> mono-vault/system/Documentation.md
```

The vault is gitignored, so this sync is local state only. Verify with:

```bash
cmp Documentation.md mono-vault/system/Documentation.md
```

## Verification

Full test suite:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
420 passed in 9.99s
```

## Suggested Next Steps

1. Add an `axiom-queue` handler that wraps `axiom_fetch.ingest()` so URL ingestion can be submitted as a job.
2. Add upload ingestion for `.md` and `.txt` before heavier PDF/DOCX work.
3. Decide the retrieval/index strategy before adding embeddings to chunk metadata.

## Local Environment

| Item | Value |
|---|---|
| OS | Fedora 44 |
| Python | 3.14+ |
| Repo | `/home/mono/Projects/mono-axiom` |
| Vault | `/home/mono/Projects/mono-axiom/mono-vault` |

*This file is updated only after features are confirmed working. Do not pre-document unbuilt work.*
