---
description: Update CHANGELOG.md from the commits since the last tag.
---

# /changelog

Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/).

1. List commits since the last tag: `git log $(git describe --tags --abbrev=0)..HEAD --oneline`.
2. Map Conventional Commit types to sections:
   - `feat` → Added (or Changed, if it modifies existing behavior)
   - `fix` → Fixed
   - `fix(security)` or security-related → Security
   - `refactor`, `perf`, `chore` → Changed only when users notice it; otherwise skip
3. One imperative line per change, written for users, not for the team.
4. Insert under `[Unreleased]`.
5. Show the diff and wait for approval before writing.
