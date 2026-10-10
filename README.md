# claude-code-harness

A tested, defense-in-depth harness for [Claude Code](https://docs.claude.com/en/docs/claude-code/overview): permission tiers, guard hooks, review and security agents, workflow commands and skills.

It is the generic version of the setup I run across my own projects, extracted after months of daily agent-driven development. Every rule in it exists because something went wrong without it.

## Why

An agent with shell access needs the same thing a new engineer with production access needs: clear rules, and guardrails that do not depend on remembering the rules.

Three ideas shape this harness:

1. **Prose rules get ignored; hooks do not.** A rule written in `CLAUDE.md` is a suggestion. A `PreToolUse` hook that exits with code 2 is a wall. Anything that must never happen is enforced by a hook and explained by a skill.
2. **Guards fail closed.** Claude Code only blocks on exit code 2, so a guard that crashes with any other code silently allows the command. Every hook here turns its own failures into a block.
3. **Precision over blanket denies.** A blanket `deny` on `rm -rf` blocked eleven legitimate commands in three weeks (`rm -rf dist` before a build, mutation-test scratch copies) and zero dangerous ones. A blanket deny on `.env.*` blocked dozens of reads of `.env.example`. Over-blocking trains people to switch guardrails off, so each guard targets exactly the dangerous cases and is tested against the legitimate ones.

## What is inside

```
.claude/
├── settings.json            permission tiers (allow / ask / deny) + hook wiring
├── hooks/
│   ├── commit_guard.py      protected branches, merge-only branches, Conventional Commits
│   ├── rm_guard.py          blocks rm on root, home, project root and source folders
│   └── secret_file_guard.py blocks shell access to .env, keys and credential files
├── agents/
│   ├── code-reviewer.md     severity-ranked review that must quote every finding
│   └── security-auditor.md  OWASP-oriented audit with a PASS/FAIL verdict
├── commands/                /commit /review /security-audit /dry-run /changelog /release
├── skills/
│   ├── dry-run-guard/       simulate before any destructive or external operation
│   ├── prd/                 PRD process with a mandatory premise check (Phase 0)
│   └── commit-hygiene/      the rules commit_guard.py enforces, explained
└── rules/code-style.md      file and function size thresholds for reviews
tools/env_inspect.py         read a .env with secrets redacted
templates/                   CLAUDE.md and PRD templates
tests/                       pytest suite for every guard
```

### Permission tiers

| Tier | Examples | Why |
|---|---|---|
| **allow** | git read and local commits, tests, linters, builds | Fast loop for everything reversible and local |
| **ask** | `git push`, PRs, releases, deploys, `terraform apply`, cloud IAM and secrets | Anything visible to others or hard to undo needs a human |
| **deny** | `sudo`, force push, `reset --hard`, reading `.env` and keys | Never, regardless of context |

### Guard hooks

| Hook | Blocks | Allows (tested) |
|---|---|---|
| `commit_guard.py` | Commits on `main`; direct commits on `develop`; non-conventional messages | Feature branches; the commit that concludes a conflicted merge on `develop` |
| `rm_guard.py` | `rm` on `/`, `~`, home directories, the project root, `src`, `.git`, `.claude`, `docs`, `migrations` | `rm -rf dist`, `node_modules`, caches, temp copies, single files |
| `secret_file_guard.py` | `cat .env`, `.env.local`, `.env.production`, `*.pem`, `*.key`, service-account and credential JSON, SSH keys | `.env.example`/`.sample`/`.template`, prose that mentions `.env`, the redacting inspector |

Known limitation, stated on purpose: guards read the literal command. `rm -rf $DIR`, where `$DIR` expands to a protected path, is not caught. Version control is the safety net there.

### The PRD Phase 0

The most useful rule in this repo is not a hook. Before writing a PRD, every claim inherited from a ticket or plan is checked against the code, with the command that was run and a literal quote of the line found:

| Claim | Command run | Evidence | Verdict |
|---|---|---|---|

It exists because confident, written diagnoses ("this feature is missing", "this is not published") kept turning out false once someone opened the file. Checking once per session was not enough; it has to be done claim by claim. See [`.claude/skills/prd/SKILL.md`](.claude/skills/prd/SKILL.md).

## Install

```bash
git clone https://github.com/baxtercl/claude-code-harness.git
./claude-code-harness/install.sh /path/to/your/project
```

The installer never overwrites an existing `settings.json`; it writes `settings.harness.json` next to it for a manual merge. Use `--force` to overwrite the other files.

Requires Python 3.10+ (standard library only) and git.

## Configure

All guard behavior is set through the `env` block in `.claude/settings.json`:

| Variable | Default | Effect |
|---|---|---|
| `HARNESS_PROTECTED_BRANCHES` | `main` | No commits at all |
| `HARNESS_MERGE_ONLY_BRANCHES` | `develop` | Only merge conclusions |
| `HARNESS_CONVENTIONAL_COMMITS` | `1` | Enforce `type(scope): description` |
| `HARNESS_BLOCK_AI_TRAILERS` | `0` | For teams that require human-only authorship lines |
| `HARNESS_RM_PROTECTED` | `src,.git,.claude,docs,migrations` | Folder names `rm` may not remove whole |

Whether commits mention AI assistance is a team choice. The cleanest control is Claude Code's `attribution` setting; the hook option exists for teams that want it enforced.

## Test

```bash
pip install pytest ruff
pytest -q
ruff check . && ruff format --check .
```

The suite feeds each hook the same JSON event Claude Code sends and asserts on the exit code. It includes a fail-closed test (malformed input must block) and real temporary git repositories for branch and merge states. Breaking any guard turns the suite red; that was verified by sabotaging `rm_guard.py`, which failed 18 tests.

## License

MIT
