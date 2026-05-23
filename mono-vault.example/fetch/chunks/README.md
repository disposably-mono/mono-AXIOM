# fetch/chunks/

Retrievable text chunks produced by the ingestion pipeline.
One chunk per file.

Frontmatter schema:
```yaml
---
id: src-abc123def456-0000
type: fetch_chunk
source_id: src-abc123def456
chunk_index: 0
chunk_total: 12
created_at: 2026-05-23T10:00:05Z
char_count: 1847
overlap_chars: 200        # optional, absent on first chunk
tags: [research]          # optional
---
```

Body is the chunk text. Current defaults are 2000 characters per chunk
with 200 characters of overlap.
