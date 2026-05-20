# fetch/sources/

Metadata for every URL fetched or document ingested. Original content
(when re-derivable) is not stored here — just the source record.

Frontmatter schema:
```yaml
---
source_id: <uuid>
kind: url | upload
location: <url or original filename>
fetched_at: 2026-05-20T14:30:00Z
chunk_ids: [<uuid>, <uuid>, ...]
---
```
