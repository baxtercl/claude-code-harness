# <Project name>

<One paragraph: what this project is, who uses it, and what matters most when changing it.>

## Stack

- Backend: <e.g. Python 3.12, FastAPI, PostgreSQL>
- Frontend: <e.g. React, TypeScript, Vite>
- Package managers: <e.g. uv, npm only>

## Commands

| Task | Command |
|---|---|
| Install | `<...>` |
| Run locally | `<...>` |
| Lint and format | `<...>` |
| Type check | `<...>` |
| Unit tests | `<...>` |

Run lint, type check and unit tests before every commit. CI runs the same gates.

## How work flows

- Branches: `feature/*` and `bugfix/*` from `develop`. `main` only receives releases.
- Commits: Conventional Commits, one logical change each (`/commit`).
- Non-trivial features start with a PRD (`prd` skill) and its Phase 0.
- Before merging: `/review` and `/security-audit`.
- Destructive or external operations go through `/dry-run`.

## Rules the hooks enforce

These are not suggestions; the hooks in `.claude/hooks/` block them:

- No commits on protected branches, and only Conventional Commit messages.
- No `rm` on the project root, the home directory or source folders.
- No reading `.env` or credential files. Use `python3 tools/env_inspect.py .env` instead.

## Conventions

- <code style rules, size thresholds, naming>
- <patterns that are mandatory in this codebase>

## Out of scope for agents

- <things only humans do here: production data changes, billing, legal text>
