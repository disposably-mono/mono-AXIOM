# fetch/chunks/

Retrievable text chunks produced by the ingestion pipeline.
One chunk per file.

Frontmatter schema:
```yaml
---
chunk_id: <uuid>
source_id: <uuid>
position: <int>           # ordinal within source
embedding_model: <name>   # if/when embeddings are added
---
```

Body is the chunk text. Chunk size and overlap policy lives in
`system/config/fetch.md`.
