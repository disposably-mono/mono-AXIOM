# fetch/sources/

Metadata for every URL fetched or document ingested. Original content
(when re-derivable) is not stored here — just the source record.

Frontmatter schema:
```yaml
---
id: src-abc123def456
type: fetch_source
status: pending | succeeded | failed
url: https://example.com/article
created_at: 2026-05-23T10:00:00Z
updated_at: 2026-05-23T10:00:05Z
fetched_at: 2026-05-23T10:00:05Z   # optional, succeeded sources
content_type: text/html             # optional
title: Example Article              # optional
error: HTTP 404                     # optional, failed sources
chunk_count: 12                     # optional, succeeded sources
tags: [research]                    # optional
---
```
