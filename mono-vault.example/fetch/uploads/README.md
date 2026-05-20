# fetch/uploads/

Raw user-uploaded files (PDF, .docx, .txt, .md) before chunking.
Filenames preserve the original where possible, prefixed with a slug.

This is the only directory in the vault that may contain non-Markdown files.
Everything derived from these uploads lands in `fetch/chunks/` as Markdown.
