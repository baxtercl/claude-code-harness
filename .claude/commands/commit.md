---
description: Create a Conventional Commit after reviewing what is staged.
---

# /commit

1. Run `git status` and `git diff --staged`. If nothing is staged, show the status and ask what to add.
2. Write the message as a Conventional Commit:
   ```
   <type>(<scope>): <imperative description, lowercase, no period>

   [optional body explaining why, not what]
   ```
   Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
3. Show the exact message and wait for approval.
4. Commit with `git commit -m "<subject>"` (add `-m "<body>"` for a body).
5. Show `git log -1 --stat` so the user sees what landed.

The `commit_guard.py` hook enforces branch protection and the message format, so a rejected commit comes back with the reason. Fix the cause; do not work around the hook.
