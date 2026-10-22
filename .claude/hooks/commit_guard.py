#!/usr/bin/env python3
"""PreToolUse guard (matcher: Bash): commit hygiene and branch protection.

Blocks a `git commit` when:
  1. The current branch is protected (default: main). Work happens on
     feature/* or bugfix/* branches.
  2. The current branch only accepts merges (default: develop) and no merge
     is in progress. The commit that concludes a conflicted merge is allowed.
  3. The `-m` message is not a Conventional Commit (can be turned off).
  4. Optionally, the message carries an AI attribution trailer or footer line
     (`Co-Authored-By: Claude ...`, `Generated with ...`). Some teams require
     human-only authorship lines; this is off by default because the
     harness-level `attribution` setting is the cleaner control. Human
     co-authors and messages that merely mention an assistant are allowed.

A command is a commit only when `git commit` is the program of one of its
segments (split on `;`, `&&`, `||`, `|`, newlines and subshells, outside quotes).
The message comes from that segment alone, so text that mentions a commit, or
the `-m` of another program chained before it, is never mistaken for one.
`bash -c '...'`, `sh -c` and `eval` are looked into as well.

Known limitations: heredoc bodies are skipped, `$(...)` inside double quotes is
not expanded, and git aliases (`git ci`) are not recognised.

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
from typing import Any

from _common import (
    ALLOW,
    block,
    command_of,
    env_flag,
    env_list,
    run_guard,
    split_segments,
    tokenize,
)

GUARD = "commit-guard"
MAX_NESTING = 3

CONVENTIONAL = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([a-z0-9._/-]+\))?!?: \S"
)
# "claude" alone is not in the list, so messages mentioning CLAUDE.md stay valid.
AI_TRAILERS = re.compile(
    r"co-authored-by|generated[ -]with|generated-by|assisted-by|noreply@anthropic"
    r"|claude code|claude\.ai|🤖",
    re.IGNORECASE,
)

ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Prefixes that run the next word as a command, plus shell keywords that precede one.
PREFIXES = {"sudo", "time", "nohup", "command", "xargs", "exec", "env"}
PREFIXES |= {"if", "then", "else", "elif", "do", "while", "until", "!"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
GIT_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--config-env",
}
# `-m`, optionally clustered with value-less flags (`-am`, `-nm`) or glued to its value (`-mfix`).
SHORT_MESSAGE = re.compile(r"^-[aenpsvqzio]*m(.*)$")
# What `-m "$(cat <<'EOF' ... EOF)"` leaves in the argument.
SUBSTITUTED_HEREDOC = re.compile(
    r"^\$\(\s*cat\s+<<-?\s*(['\"]?)(\w+)\1\n(.*)\n\s*\2\s*\)$", re.DOTALL
)


@dataclass
class Commit:
    args: list[str]
    git_dirs: list[str]


def git_commit(args: list[str]) -> Commit | None:
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
        return Commit(args[index + 1 :], git_dirs)
    return None


def commits_in(command: str, depth: int = 0) -> list[Commit]:
    commits: list[Commit] = []
    for segment in split_segments(command):
        tokens = tokenize(segment)
        start = 0
        while start < len(tokens) and (
            ENV_ASSIGNMENT.match(tokens[start]) or tokens[start] in PREFIXES
        ):
            start += 1
        if start >= len(tokens):
            continue
        program = os.path.basename(tokens[start]).lower().removesuffix(".exe")
        args = tokens[start + 1 :]
        if program == "git":
            commit = git_commit(args)
            if commit:
                commits.append(commit)
        elif program in SHELLS or program == "eval":
            if depth >= MAX_NESTING:
                raise ValueError("shell commands nested too deeply to inspect")
            commits += nested_commits(program, args, depth + 1)
    return commits


def nested_commits(program: str, args: list[str], depth: int) -> list[Commit]:
    if program == "eval":
        return commits_in(" ".join(args), depth)
    for index, arg in enumerate(args[:-1]):
        if re.fullmatch(r"-[a-zA-Z]*c", arg):
            return commits_in(args[index + 1], depth)
    return []


def commit_message(args: list[str]) -> str | None:
    """The message given with -m/--message (paragraphs joined by a blank line), if any."""
    messages: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            break
        if arg == "--message" and index + 1 < len(args):
            messages.append(args[index + 1])
            index += 1
        elif arg.startswith("--message="):
            messages.append(arg.split("=", 1)[1])
        elif not arg.startswith("--"):
            match = SHORT_MESSAGE.match(arg)
            if match and match.group(1):
                messages.append(match.group(1))
            elif match and index + 1 < len(args):
                messages.append(args[index + 1])
                index += 1
        index += 1
    if not messages:
        return None
    heredoc = SUBSTITUTED_HEREDOC.match(messages[0])
    if heredoc:
        messages[0] = heredoc.group(3)
    return "\n\n".join(messages)


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
    commits = commits_in(command)
    if commits and env_flag("HARNESS_BLOCK_AI_TRAILERS", False) and AI_TRAILERS.search(command):
        return block(
            GUARD,
            "the commit carries an AI attribution trailer, and this project requires "
            "human-only authorship lines. Rewrite the message without it.",
        )
    for commit in commits:
        message = commit_message(commit.args)
        if message is not None:
            code = check_message(message)
            if code != ALLOW:
                return code
        repo_dir = repo_dir_for(command, str(event.get("cwd") or ""), commit.git_dirs)
        code = check_branch(repo_dir)
        if code != ALLOW:
            return code
    return ALLOW


if __name__ == "__main__":
    run_guard(GUARD, check)
