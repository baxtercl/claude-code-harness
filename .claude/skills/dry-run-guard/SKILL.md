---
name: dry-run-guard
description: Use before any destructive or externally visible operation, even if the user did not ask for it. Deploys, database migrations, bulk deletes, scraping or crawling runs, publishing to a registry, and bulk emails or notifications. Requires a simulated run and explicit confirmation before the real one.
---

# Dry-run guard

## When it applies

Any command that:

- Changes cloud infrastructure (`terraform apply`, `kubectl apply`, a production deploy).
- Applies database migrations or runs `DROP`, `DELETE`, `TRUNCATE` or `ALTER`.
- Starts a crawl or scraping job against a live site.
- Deletes files in bulk.
- Publishes to a registry (`npm publish`, `uv publish`, `gh release create`).
- Sends notifications or emails to more than one recipient.
- Has any irreversible effect on a shared resource.

## Protocol

1. **Detect** the operation and name what it touches.
2. **Translate** it to its simulation (`--dry-run`, `--plan`, `--check`, `--noop`).
3. **Run** the simulation.
4. **Show** the full output: what changes, how many records, expected cost and duration.
5. **Wait** for an explicit confirmation such as "yes, run it for real".
6. **Run** the real operation.
7. **Report** an observable result: a log line, a URL, a hash, a row count.

## Rules

- If the tool has no native dry run, build one: `SELECT COUNT(*) ... WHERE <same filter>` before a `DELETE`, `ls` of the glob before an `rm`.
- If the dry run fails, the real run does not happen.
- "The user is in a hurry" is not a reason to skip this.
