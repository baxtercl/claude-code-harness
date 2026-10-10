---
description: Security audit of the current branch. Blocking before merging to a protected branch.
---

# /security-audit

1. Determine the scope: `git diff <base>...HEAD` against the target branch.
2. Hand it to the **security-auditor** agent.
3. Check for tracked files that should be ignored: `git ls-files -ci --exclude-standard`.
4. Report the findings table and a `PASS` / `FAIL` verdict.

If a committed secret is found: stop, tell the user to rotate it, and only then plan the history rewrite.
