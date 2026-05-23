# axiom-fetch

**Layer 3 — Retrieval.**

Web retrieval, document ingestion, and RAG chunking. Pulls content from URLs and uploaded files, normalizes it to Markdown, and produces searchable chunks.

## Responsibility

- Fetch web pages and parse to clean Markdown
- Ingest PDF, `.docx`, `.txt`, and `.md` uploads
- Chunk content with overlap for retrieval
- Persist sources and chunks to `/mono-vault/fetch/`

## Status

Phase 3 in progress. URL ingestion for supported document types is implemented and tested:

- HTTP fetch with redirect support, timeout handling, user agent, and response size cap
- HTML extraction via BeautifulSoup + markdownify
- Plain-text extraction
- PDF extraction via pypdf
- DOCX extraction via python-docx
- Fixed-character chunking with overlap and soft boundary handling
- `ingest(url, store)` pipeline that writes `fetch/sources/<source_id>.md` and `fetch/chunks/<source_id>-NNNN.md`
- `scripts/demo_axiom_fetch.py` end-to-end demo for HTML/TXT/PDF/DOCX ingestion

Still deferred: public file/upload ingestion, embeddings, retrieval/search, and queue-handler integration.
