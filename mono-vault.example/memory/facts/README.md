# memory/facts/

Extracted, deduplicated facts the model can recall in future sessions.
One fact per file. Filenames are short, descriptive slugs.

Frontmatter schema:
```yaml
---
fact_id: <uuid>
source: <conversation_id | url | upload>
confidence: 0.0 - 1.0
created_at: 2026-05-20T14:30:00Z
tags: []
---
```

Body is a single sentence or paragraph stating the fact.
