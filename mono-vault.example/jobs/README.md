# jobs/

One Markdown file per background job. The queue layer reads, updates,
and archives these.

Frontmatter schema:
```yaml
---
job_id: <uuid>
kind: fetch | summarize | embed | export | ...
status: pending | running | succeeded | failed
created_at: 2026-05-20T14:30:00Z
started_at: <iso or null>
finished_at: <iso or null>
attempts: 0
max_attempts: 3
---
```

Body holds job-specific parameters and the final result or error trace.
