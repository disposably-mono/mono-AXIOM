# memory/conversations/

One Markdown file per chat session. Filename is the session slug:
`2026-05-20-mono-axiom-scaffold.md`

Frontmatter schema:
```yaml
---
session_id: <uuid>
started_at: 2026-05-20T14:30:00Z
ended_at: 2026-05-20T15:45:00Z
provider: anthropic | openai | ollama | mixed
tags: [scaffolding, phase-0]
---
```

Body is the full transcript in Markdown.
