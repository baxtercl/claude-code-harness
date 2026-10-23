# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.3.1] - 2026-10-23

### Fixed

- `data_guard.py` looked for `apply_patch` headers in every Bash command, so under Claude Code a
  commit message that quoted one was blocked. That scan now only runs for Codex events.

## [0.3.0] - 2026-10-23

### Added

- Codex support. The guard hooks run unchanged under Codex: `.codex/hooks.json` wires the Bash
  guards, `install.sh` copies it, and a test keeps it in step with `.claude/settings.json`.
  Verified against Codex CLI 0.163. See "Claude Code and Codex" in the README.

### Changed

- The project root comes from `CLAUDE_PROJECT_DIR`, then `HARNESS_PROJECT_DIR`, then the git root
  of the event's `cwd`, so the guards no longer depend on a Claude Code variable.
- `data_guard.py` reads the files named in a Codex `apply_patch`, and where Claude Code would ask
  it blocks under Codex, which has no "ask" decision.
- A command given as an argv array is joined before it is inspected.

## [0.2.1] - 2026-10-23

### Fixed

- `commit_guard.py` lost the backslashes of unquoted Windows paths (`git -C C:\repo commit`,
  `cd C:\repo && git commit`), so on Windows it inspected a non-existent directory. On Windows it
  now tokenizes without POSIX escapes. The CI also runs the suite on Windows.

## [0.2.0] - 2026-10-22

### Added

- `data_guard.py`, an optional guard for live application data (SQLite files, uploads). It is
  inactive until `HARNESS_DATA_PATHS` is set and is not wired in the default `settings.json`.
  It blocks destructive commands, redirections, `sqlite3` writes and file-tool edits on the
  protected paths, requires a recent backup before the apply flag, and can block or ask for
  commands matching `HARNESS_DATA_BLOCK_PATTERNS` and `HARNESS_DATA_ASK_PATTERNS`. See the README.

### Fixed

- `rm_guard.py` did not recognise Windows project paths: POSIX tokenizing dropped the
  backslashes, so `rm -rf C:\Users\name\project` was allowed. Paths are now normalised, drive
  roots and `C:\Users\name` are protected, and `..` segments are resolved.
- `commit_guard.py` treated any command whose text contained `git commit` as a commit and took
  the first `-m` of the whole command as its message. A new shared analyser (`_shell.py`) now
  splits the line into commands outside quotes, skips comments and heredoc bodies, and looks
  inside `bash -c`, `eval`, shells fed by a heredoc or a pipe, `$(...)` in double quotes and
  wrappers such as `sudo -u x`, `env -i`, `nice`, `timeout`, `xargs` and `find -exec`. A command
  is a commit only when `git commit` is its program, and the message is read from that command
  (`-m`, `-am`, `-mMESSAGE`, `--message=`, `-F -`, `-F <file>`, `--trailer`, or a heredoc through
  command substitution). A command it cannot read is blocked.
- With `HARNESS_BLOCK_AI_TRAILERS=1`, `commit_guard.py` blocked any mention of an assistant's
  product name in the command. It now checks only trailer and footer lines of the message, so
  human co-authors and messages that merely mention an assistant are allowed.
- The repository of a commit follows `cd`, `pushd`, `-C`, `GIT_DIR` and `--git-dir`; a directory
  that does not exist yet falls back to the working directory. Line continuations, `$'...'`,
  unquoted heredoc bodies with `$(...)`, `bash -c -l`, `fish -c`, `su -c`, `cmd /c`,
  `powershell -Command`, more wrappers and abbreviated long options are handled, and a
  commit message given as a heredoc with parentheses, git's own `Merge ...` subjects and
  messages held in a variable are no longer rejected.
- `rm_guard.py` now uses the same analyser, so `rm` is found inside `bash -c`, subshells,
  backticks, `sudo`/`env`/`xargs` and behind `&`; it also blocks `rm -rf //`, `/*`, quote
  concatenation such as `s"r"c`, `C:\Windows` and `C:\Program Files`, and compares protected
  names on Windows paths case-insensitively.

## [0.1.0] - 2026-10-10

### Added

- Initial release: permission tiers, `commit_guard.py`, `rm_guard.py`, `secret_file_guard.py`,
  the `code-reviewer` and `security-auditor` agents, the workflow commands, the `dry-run-guard`,
  `prd` and `commit-hygiene` skills, `tools/env_inspect.py` and the pytest suite.
