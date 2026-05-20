# axiom-store

**Layer 1 — Persistent state.**

A Markdown-backed file store with a TCP interface and write-through cache. Every persistent change in Mono-AXIOM flows through this layer and lands as a `.md` file in `/mono-vault/`.

## Responsibility

- Read and write Markdown files with YAML frontmatter
- Provide a TCP server other layers can connect to
- Maintain an in-memory write-through cache
- Validate frontmatter schemas per vault content type

## Status

Not yet implemented. Phase 1 (Weeks 3–5).
