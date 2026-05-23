# Handoff

Session date: 2026-05-23

## Summary

This session extends Phase 3 `axiom-fetch` beyond the original URL-ingestion MVP:

- PDF extraction is implemented with `pypdf`.
- DOCX extraction is implemented with `python-docx`.
- The fetch pipeline now records PDF/DOCX extraction failures as failed source metadata instead of crashing.
- `scripts/demo_axiom_fetch.py` demonstrates end-to-end ingestion for generated HTML, TXT, PDF, and DOCX documents through a live `axiom-store`.
- Project docs were updated: `README.md`, `PRD.md`, `Documentation.md`, `Handoff.md`, and `axiom-fetch/README.md`.

## Implemented State

### PDF ingestion

New file:

```text
axiom-fetch/pdf_extractor.py
```

Behavior:

- Opens PDF bytes with `pypdf.PdfReader`.
- Rejects encrypted PDFs with a clear `ValueError`.
- Uses PDF metadata title when present.
- Extracts text page-by-page and joins page boundaries with blank lines.
- Raises `EmptyExtractionError` when no extractable text is present, which covers scanned/image-only PDFs for this phase.

### DOCX ingestion

New file:

```text
axiom-fetch/docx_extractor.py
```

Behavior:

- Opens DOCX bytes with `python-docx`.
- Uses core-properties title when present.
- Walks document body blocks in order.
- Converts paragraphs to Markdown-ish text.
- Converts Heading 1-6 styles to Markdown headings.
- Converts simple bullet/numbered list styles.
- Converts tables to GitHub-flavored Markdown tables.
- Raises clear errors for invalid or empty DOCX files.

### Extractor dispatch

`axiom-fetch/extractor.py` now dispatches:

```text
text/html
text/plain
application/pdf
application/vnd.openxmlformats-officedocument.wordprocessingml.document
```

### Pipeline failure handling

`axiom-fetch/pipeline.py` now catches extraction-domain `ValueError`s and `pypdf.errors.PdfReadError`, writing a failed `FETCH_SOURCE` record with the error message. This keeps malformed/encrypted/empty documents visible in the vault.

### Dependencies

`pyproject.toml` now includes:

```text
pypdf>=4.0
python-docx>=1.1
```

### Demo script

New file:

```text
scripts/demo_axiom_fetch.py
```

Run:

```bash
python -m axiom_store.server --vault /home/mono/Projects/mono-axiom/mono-vault -v
python scripts/demo_axiom_fetch.py
```

The demo starts a local HTTP server, serves generated HTML/TXT/PDF/DOCX documents, ingests each with `axiom_fetch.ingest()`, asserts the written source/chunk files, and prints vault paths for inspection. It supports `--host`, `--port`, and `--vault`.

## Tests Added

New:

```text
axiom-fetch/tests/test_pdf_extractor.py
axiom-fetch/tests/test_docx_extractor.py
```

Updated:

```text
axiom-fetch/tests/test_extractor.py
axiom-fetch/tests/test_pipeline.py
```

Coverage includes:

- PDF dispatch and content-type parameters.
- PDF metadata title extraction.
- PDF empty/encrypted failure behavior.
- DOCX dispatch and content-type parameters.
- DOCX title, headings, paragraphs, and tables.
- DOCX invalid/empty failure behavior.
- Pipeline failure records for unreadable PDF/DOCX.
- Pipeline success path for real generated DOCX bytes.

## Verification

Lint:

```bash
python -m ruff check pyproject.toml axiom-fetch scripts/demo_axiom_fetch.py
```

Result:

```text
All checks passed!
```

Full test suite:

```bash
python -m pytest
```

Result:

```text
439 passed in 9.20s
```

Fetch demo smoke run:

```bash
python scripts/demo_axiom_fetch.py --vault <tmp-vault> --port 7071
```

Result:

```text
All axiom-fetch demo ingests passed.
```

## Current Phase 3 Status

Working:

- URL ingestion via `ingest(url, store)`.
- HTML, plain text, PDF, and DOCX extraction.
- Chunk persistence into `fetch/chunks/`.
- Source persistence into `fetch/sources/`.
- Human-facing fetch demo script.

Still deferred:

- Public file/upload ingestion API (`ingest_file`).
- Queue handler wrapper around `axiom_fetch.ingest()`.
- Embeddings and retrieval/search.
- OCR for scanned PDFs.

## Local Environment

| Item | Value |
|---|---|
| OS | Fedora 44 |
| Python | 3.14.4 |
| Repo | `/home/mono/Projects/mono-axiom` |
| Vault | `/home/mono/Projects/mono-axiom/mono-vault` |

*This file is updated only after features are confirmed working. Do not pre-document unbuilt work.*
