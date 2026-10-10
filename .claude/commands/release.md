---
description: Prepare a release with Gitflow and Semantic Versioning.
---

# /release

## Preconditions

- On `develop`, clean working tree, CI green.
- `/security-audit` returned `PASS`.

## Steps

1. Agree on the version with the user: MAJOR (breaking), MINOR (backward-compatible feature), PATCH (fixes only).
2. `git switch -c release/vX.Y.Z develop`
3. Bump the version where it is declared (`pyproject.toml`, `package.json`).
4. In `CHANGELOG.md`, move `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` and open a new empty `[Unreleased]`.
5. Commit: `chore(release): vX.Y.Z`.
6. Merge into `main` with `--no-ff` and tag: `git tag -a vX.Y.Z -m "Release X.Y.Z"`.
7. Merge back into `develop` with `--no-ff`.
8. Delete the release branch.
9. Ask before pushing: `git push origin main develop --tags`.

## Rules

- Never push without explicit approval. Never force-push `main` or `develop`.
- If something breaks after the merge to `main`, open a hotfix branch. Do not amend published history.
