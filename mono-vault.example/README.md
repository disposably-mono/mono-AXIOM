# mono-vault.example

The committed **skeleton** for the Mono-AXIOM vault.

`scripts/bootstrap_vault.py` copies this directory to `./mono-vault/` (or `$VAULT_PATH`) on first setup. The real vault is gitignored and lives only on your machine.

## Structure

```
mono-vault/
├── memory/
│   ├── conversations/   ← one .md per chat session
│   ├── facts/           ← extracted, deduplicated facts
│   └── summaries/       ← rolling summaries when context overflows
├── personas/            ← system prompts and behavioral profiles
├── fetch/
│   ├── sources/         ← original URL/document metadata
│   ├── chunks/          ← retrievable text chunks for RAG
│   └── uploads/         ← raw user-uploaded files
├── jobs/                ← queue state, one .md per job
├── system/              ← config, routing rules, schemas
└── exports/             ← generated export bundles
```

## Conventions

- Every file is Markdown with YAML frontmatter.
- Filenames are slugs (lowercase, hyphenated, no spaces).
- Timestamps in frontmatter use ISO 8601 (`2026-05-20T14:30:00Z`).
- Any new content type requires a documented schema in `system/schemas/` before code is written to produce it.

## Editing by hand

You can open this vault in Obsidian or any text editor. The system tolerates manual edits — `axiom-store` reads from disk on each request and respects whatever's there. If you delete a fact or rewrite a summary, the next interaction will see your change.

The one thing **not** to do is reach around `axiom-store` to write files from other code. All persistent writes must go through the store so the cache stays coherent.
