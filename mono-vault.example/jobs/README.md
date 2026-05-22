# jobs/

One Markdown file per background job. The queue layer reads, updates,
and archives these.

Frontmatter schema:
```yaml
---
id: <uuid>
kind: echo | noop | fetch | summarize | embed | export | ...
status: pending | running | succeeded | failed | dead
created_at: 2026-05-20T14:30:00Z
updated_at: 2026-05-20T14:30:00Z
attempts: 0
max_attempts: 3
payload: {}
result: {}              # optional, set on success
error: <message>        # optional, set on failure/dead
next_attempt_at: <iso>  # optional, set while waiting for retry
worker_id: <id>         # optional, set while running
claimed_at: <iso>       # optional, set while running
tags: []                # optional
---
```

Body holds job-specific parameters and the final result or error trace.
