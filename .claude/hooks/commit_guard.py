#!/usr/bin/env python3
"""PreToolUse guard (matcher: Bash): commit hygiene and branch protection.

Blocks a `git commit` when:
  1. The current branch is protected (default: main). Work happens on
     feature/* or bugfix/* branches.
  2. The current branch only accepts merges (default: develop) and no merge
     is in progress. The commit that concludes a conflicted merge is allowed.
  3. The `-m` message is not a Conventional Commit (can be turned off).
  4. Optionally, the message carries AI attribution trailers. Some teams
     require human-only authorship lines; this is off by default because the
     harness-level `attribution` setting is the cleaner control.

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
from typing import Any

from _common import ALLOW, block, command_of, env_flag, env_list, run_guard, tokenize

GUARD = "commit-guard"

# Matches `git commit`, `git -C dir commit`, `git -c k=v commit`, `git --no-pager commit`.
GIT_COMMIT = re.compile(r"\bgit((\s+-[Cc]\s+\S+)|(\s+--[a-z-]+(=\S+)?))*\s+commit\b")
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


def repo_dir_for(command: str, cwd: str) -> str:
    repo_dir = cwd or os.getcwd()
    cd_match = re.match(r"^\s*cd\s+([^\s;&|]+)", command)
    if cd_match:
        repo_dir = os.path.join(repo_dir, os.path.expanduser(cd_match.group(1)))
    c_match = re.search(r"\bgit\s+-C\s+(\S+)", command)
    if c_match:
        repo_dir = os.path.join(repo_dir, os.path.expanduser(c_match.group(1)))
    return repo_dir


def git(repo_dir: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo_dir, *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def commit_message(command: str) -> str | None:
    tokens = tokenize(command)
    for i, token in enumerate(tokens):
        if token in {"-m", "--message"} and i + 1 < len(tokens):
            return tokens[i + 1]
        if token.startswith("--message="):
            return token.split("=", 1)[1]
    return None


def check(event: dict[str, Any]) -> int:
    command = command_of(event)
    if not GIT_COMMIT.search(command):
        return ALLOW

    if env_flag("HARNESS_BLOCK_AI_TRAILERS", False) and AI_TRAILERS.search(command):
        return block(
            GUARD,
            "the commit carries an AI attribution trailer, and this project requires "
            "human-only authorship lines. Rewrite the message without it.",
        )

    message = commit_message(command)
    if (
        message is not None
        and env_flag("HARNESS_CONVENTIONAL_COMMITS", True)
        and not CONVENTIONAL.match(message)
    ):
        return block(
            GUARD,
            f"{message.splitlines()[0]!r} is not a Conventional Commit. "
            "Use '<type>(<scope>): <description>', e.g. 'fix(api): handle empty query'.",
        )

    repo_dir = repo_dir_for(command, str(event.get("cwd") or ""))
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


if __name__ == "__main__":
    run_guard(GUARD, check)
