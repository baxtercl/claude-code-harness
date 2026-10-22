#!/usr/bin/env python3
"""PreToolUse guard (matcher: Bash): commit hygiene and branch protection.

Blocks a `git commit` when:
  1. The current branch is protected (default: main). Work happens on
     feature/* or bugfix/* branches.
  2. The current branch only accepts merges (default: develop) and no merge
     is in progress. The commit that concludes a conflicted merge is allowed.
  3. The message is not a Conventional Commit (can be turned off).
  4. Optionally, the message carries an AI attribution trailer or footer line
     (a `Co-Authored-By` naming an assistant, a `Generated with ...` footer).
     Some teams require human-only authorship lines; this is off by default
     because the harness-level `attribution` setting is the cleaner control.
     Human co-authors and messages that merely mention an assistant are allowed.

A command is a commit only when `git commit` is the program of one of the commands
on the line (see _shell.py: separators, nested shells, wrappers such as `sudo` or
`env`, `find -exec`). The message comes from that command alone, so text that
mentions a commit, or the `-m` of another program chained before it, is never
mistaken for one. The message may be given with -m, with `-F -` (a heredoc), with
`-F <file>` (read when the file exists) and with --trailer.

Known limitations: git aliases (`git ci`) are not recognised, and neither are
commits run on another machine (`ssh host 'git commit'`).

Configuration (environment):
  HARNESS_PROTECTED_BRANCHES   default "main"
  HARNESS_MERGE_ONLY_BRANCHES  default "develop"
  HARNESS_CONVENTIONAL_COMMITS default on
  HARNESS_BLOCK_AI_TRAILERS    default off
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _common import ALLOW, block, command_of, env_flag, env_list, run_guard
from _shell import iter_commands, program_name

GUARD = "commit-guard"
MAX_MESSAGE_FILE = 100_000

CONVENTIONAL = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([a-z0-9._/-]+\))?!?: \S"
)
# Only trailer and footer lines count: a message that says "update CLAUDE.md" or
# "document Claude Code hooks" is not an attribution.
AI_NAMES = r"(claude|anthropic|openai|chatgpt|gpt-?\d|codex|copilot|gemini|cursor|devin)"
AI_TRAILER = re.compile(
    rf"^(co-authored-by|generated-by|assisted-by|signed-off-by):.*\b{AI_NAMES}", re.IGNORECASE
)
AI_FOOTER = re.compile(
    rf"^(generated|created|written|made|co-created) (with|by) .*\b{AI_NAMES}|🤖", re.IGNORECASE
)

GIT_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--config-env",
}
# `-m` or `-F`, optionally clustered with value-less flags (`-am`) or glued to the value.
SHORT_VALUE = re.compile(r"^-[aenpsvqzio]*([mF])(.*)$")
# What `-m "$(cat <<'EOF' ... EOF)"` leaves in the argument.
SUBSTITUTED_HEREDOC = re.compile(
    r"^\$\(\s*cat\s+<<-?\s*(['\"]?)(\w+)\1\n(.*)\n\s*\2\s*\)$", re.DOTALL
)


@dataclass
class Commit:
    args: list[str]
    git_dirs: list[str]
    stdin: str


def git_commit(args: list[str], stdin: str) -> Commit | None:
    """The commit invocation behind `git <global options> commit <args>`, if it is one."""
    git_dirs: list[str] = []
    index = 0
    while index < len(args) and args[index].startswith("-"):
        option = args[index]
        if option in GIT_OPTIONS_WITH_VALUE:
            if option == "-C" and index + 1 < len(args):
                git_dirs.append(args[index + 1])
            index += 1
        index += 1
    if index < len(args) and args[index] == "commit":
        return Commit(args[index + 1 :], git_dirs, stdin)
    return None


def commits_in(command: str) -> list[Commit]:
    commits = []
    for found in iter_commands(command):
        if program_name(found.tokens[0]) == "git":
            commit = git_commit(found.tokens[1:], found.stdin)
            if commit:
                commits.append(commit)
    return commits


def read_message_file(path: str, repo_dir: str) -> str:
    candidate = Path(repo_dir) / os.path.expanduser(path)
    try:
        if candidate.is_file() and candidate.stat().st_size <= MAX_MESSAGE_FILE:
            return candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def commit_message(commit: Commit, repo_dir: str) -> str | None:
    """The message from -m, -F and --trailer (paragraphs joined by a blank line), if given."""
    messages: list[str] = []
    trailers: list[str] = []
    args = commit.args
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            break
        flag, value = "", ""
        if arg in {"--message", "--file", "--trailer"} and index + 1 < len(args):
            flag, value = arg, args[index + 1]
            index += 1
        elif arg.startswith(("--message=", "--file=", "--trailer=")):
            flag, value = arg.split("=", 1)
        elif not arg.startswith("--") and (short := SHORT_VALUE.match(arg)):
            letter, glued = short.groups()
            flag = "--message" if letter == "m" else "--file"
            value = glued
            if not glued and index + 1 < len(args):
                value = args[index + 1]
                index += 1
        if flag == "--message":
            messages.append(value)
        elif flag == "--trailer":
            trailers.append(value)
        elif flag == "--file":
            text = commit.stdin if value == "-" else read_message_file(value, repo_dir)
            if text:
                messages.append(text)
        index += 1
    if not messages and not trailers:
        return None
    if messages:
        heredoc = SUBSTITUTED_HEREDOC.match(messages[0])
        if heredoc:
            messages[0] = heredoc.group(3)
    return "\n\n".join([*messages, *trailers])


def repo_dir_for(command: str, cwd: str, git_dirs: list[str]) -> str:
    repo_dir = cwd or os.getcwd()
    cd_match = re.match(r"^\s*cd\s+([^\s;&|]+)", command)
    if cd_match:
        repo_dir = os.path.join(repo_dir, os.path.expanduser(cd_match.group(1)))
    for git_dir in git_dirs:
        repo_dir = os.path.join(repo_dir, os.path.expanduser(git_dir))
    return repo_dir


def git(repo_dir: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo_dir, *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def check_message(message: str) -> int:
    lines = [line.strip() for line in message.splitlines()]
    if env_flag("HARNESS_BLOCK_AI_TRAILERS", False):
        for line in lines:
            if AI_TRAILER.match(line) or AI_FOOTER.search(line):
                return block(
                    GUARD,
                    f"{line!r} is an AI attribution line, and this project requires "
                    "human-only authorship lines. Rewrite the message without it.",
                )
    subject = next((line for line in lines if line), "")
    if env_flag("HARNESS_CONVENTIONAL_COMMITS", True) and not CONVENTIONAL.match(subject):
        return block(
            GUARD,
            f"{subject!r} is not a Conventional Commit. "
            "Use '<type>(<scope>): <description>', e.g. 'fix(api): handle empty query'.",
        )
    return ALLOW


def check_branch(repo_dir: str) -> int:
    branch = git(repo_dir, "branch", "--show-current")
    if not branch:
        return ALLOW

    if branch in env_list("HARNESS_PROTECTED_BRANCHES", "main"):
        return block(
            GUARD,
            f"'{branch}' is protected. Create a feature/* or bugfix/* branch and merge it instead.",
        )

    if branch in env_list("HARNESS_MERGE_ONLY_BRANCHES", "develop"):
        git_dir = git(repo_dir, "rev-parse", "--absolute-git-dir")
        if not git_dir or not os.path.exists(os.path.join(git_dir, "MERGE_HEAD")):
            return block(
                GUARD,
                f"'{branch}' only receives merges. Work on a feature/* or bugfix/* branch. "
                "(Concluding a conflicted merge is allowed automatically.)",
            )
    return ALLOW


def check(event: dict[str, Any]) -> int:
    command = command_of(event)
    for commit in commits_in(command):
        repo_dir = repo_dir_for(command, str(event.get("cwd") or ""), commit.git_dirs)
        message = commit_message(commit, repo_dir)
        if message is not None:
            code = check_message(message)
            if code != ALLOW:
                return code
        code = check_branch(repo_dir)
        if code != ALLOW:
            return code
    return ALLOW


if __name__ == "__main__":
    run_guard(GUARD, check)
