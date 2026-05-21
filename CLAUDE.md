# autoresearch — project instructions

This project has a **persistent LLM wiki** at `wiki/`. Read it before starting
work, and update it when you learn something non-obvious.

## Wiki contract (must-read)

@wiki/CLAUDE.md

## Wiki catalog

@wiki/index.md

## When to update the wiki

Update a wiki page (and append one line to `wiki/log.md`) whenever you learn
a fact that:

- Took >5 min to derive from raw sources, OR
- A future session would otherwise have to re-derive, OR
- Is a root-cause for a bug or a magic number you didn't know before.

Do not write to the wiki for ephemeral task state — that goes in `TaskCreate`,
not the wiki. Do not duplicate code into wiki pages — link to it.

## Linting

Run `python3 wiki/lint.py` to check for orphan pages, dangling `[[wiki-links]]`,
and stale `Updated:` dates (>90 days old).
