---
name: commit-hygiene
description: Use before any operation that creates or rewrites a commit (commit, amend, merge commit, cherry-pick, rebase with reword). Checks the configured author identity, the Conventional Commit format and the branch policy, and explains how the commit_guard hook enforces them.
---

# Commit hygiene

The rules live in two places on purpose: this skill explains them to the agent, and `.claude/hooks/commit_guard.py` enforces them deterministically. Prose can be ignored; a hook that exits with code 2 cannot.

## Before committing

1. **Identity.** `git config user.name` and `git config user.email` must be the identity the project expects. If they are not, stop and ask; do not change them silently.
2. **Branch.** Never commit to a protected branch (`HARNESS_PROTECTED_BRANCHES`, default `main`). Merge-only branches (`HARNESS_MERGE_ONLY_BRANCHES`, default `develop`) accept only the commit that concludes a merge.
3. **Message.** Conventional Commits: `<type>(<scope>): <imperative description>`. The body explains why.
4. **Scope.** One logical change per commit. If the diff mixes a refactor and a feature, split it.

## Attribution

Whether commits mention AI assistance is a team decision. Configure it once in `settings.json` with the `attribution` key. Teams that require human-only authorship lines can also set `HARNESS_BLOCK_AI_TRAILERS=1`, and the hook will reject messages that carry assistant trailers.

## After committing

Run `git log -1 --pretty=full` and confirm the author and message are what was approved.
