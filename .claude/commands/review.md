---
description: Review pending changes (staged and unstaged) with the code-reviewer agent.
---

# /review

1. Collect the diff: `git diff` and `git diff --staged`. If a pull request is open, add `gh pr diff`.
2. Hand the full diff to the **code-reviewer** agent.
3. Present the findings as a table:

| Severity | File:line | Problem | Suggestion |
|---|---|---|---|

Security is out of scope here; that is `/security-audit`.
