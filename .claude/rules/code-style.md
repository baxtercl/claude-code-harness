# Code style and size thresholds

The `code-reviewer` agent reads this file. Adjust the numbers to your codebase; what matters is that they exist, so "this file is too big" becomes a check instead of an opinion.

## File size by role (lines)

| Role | Healthy | Warning | Refactor |
|---|---|---|---|
| Route / endpoint | < 100 | 100-200 | > 200 |
| Service | < 200 | 200-350 | > 350 |
| Repository / data access | < 150 | 150-250 | > 250 |
| Agent / orchestration node | < 200 | 200-300 | > 300 |
| Client / adapter / provider | < 150 | 150-250 | > 250 |
| Schema / model | < 100 | 100-150 | > 150 |
| UI component | < 150 | 150-250 | > 250 |
| Page | < 250 | 250-400 | > 400 |
| Custom hook | < 100 | 100-200 | > 200 |

Every directory that holds code needs a row. A file cannot violate a threshold that does not exist, and the largest files in a codebase tend to live exactly where no row was written.

## Functions

No function above **60 lines**. Between 60 and 100 is a warning; above 100 it gets split.

## General

- Comments only where the logic is not obvious.
- No commented-out code; history lives in git.
- No debug `print` or `console.log` in commits.
