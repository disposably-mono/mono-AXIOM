# personas/

System prompts and behavioral profiles. Each `.md` file is a complete persona.

Frontmatter schema:
```yaml
---
persona_id: <slug>
name: <human-readable name>
default_provider: anthropic | openai | ollama
temperature: 0.0 - 1.0
---
```

Body is the system prompt itself.
