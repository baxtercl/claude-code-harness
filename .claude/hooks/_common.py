"""Shared helpers for the PreToolUse guard hooks.

The hooks run under Claude Code and under Codex. Both send the same JSON on stdin
(`tool_name`, `tool_input`, `cwd`) and block on exit code 2. They differ in three
details that are handled here: only Claude Code sets CLAUDE_PROJECT_DIR (see
`project_dir`), only Claude Code supports the "ask" decision (see `is_codex`), and
Codex edits files with an `apply_patch` tool (see `patch_paths`).

Claude Code only blocks a tool call when a hook exits with code 2. Any other
non-zero code (for example, an unhandled exception) lets the command through.
For a guard that is the wrong failure mode, so every hook here runs inside
`run_guard`, which turns unexpected errors into a block: guards fail closed.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from typing import Any

BLOCK = 2
ALLOW = 0


def read_event() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def command_of(event: dict[str, Any]) -> str:
    tool_input = event.get("tool_input") or {}
    command = tool_input.get("command") or ""
    if isinstance(command, list):  # an argv array: [bash, -lc, "..."]
        return shlex.join(str(part) for part in command)
    return str(command)


def is_codex(event: dict[str, Any]) -> bool:
    """Codex adds `turn_id` to every hook event; Claude Code does not."""
    return "turn_id" in event


def project_dir(event: dict[str, Any]) -> str:
    """The project root.

    Claude Code: CLAUDE_PROJECT_DIR. Codex sets none, and a CLAUDE_PROJECT_DIR leaked from a
    Claude session that launched it would point at the wrong project, so it is ignored there.
    Then HARNESS_PROJECT_DIR, the git root of the event's cwd, and cwd itself.
    """
    names = (
        ("HARNESS_PROJECT_DIR",)
        if is_codex(event)
        else ("CLAUDE_PROJECT_DIR", "HARNESS_PROJECT_DIR")
    )
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    cwd = str(event.get("cwd") or "")
    if cwd:
        try:
            result = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:  # git is not installed
            return cwd
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return cwd


# Header lines of an apply_patch body, also when a shell command spells the newlines as `\n`.
PATCH_FILE = re.compile(
    r"(?:^|\\n)\s*\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*(?=\\n|$)", re.M
)


def patch_paths(text: str) -> list[str]:
    """The files named in a Codex `apply_patch` body."""
    return PATCH_FILE.findall(text)


def env_list(name: str, default: str) -> list[str]:
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def tokenize(segment: str) -> list[str]:
    """Split a shell segment into tokens; fall back to whitespace on bad quoting."""
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def block(guard: str, reason: str) -> int:
    sys.stderr.write(f"BLOCKED ({guard}): {reason}\n")
    return BLOCK


def run_guard(guard: str, check: Callable[[dict[str, Any]], int]) -> None:
    try:
        code = check(read_event())
    except Exception as exc:  # noqa: BLE001 - fail closed: a crashing guard must not allow
        code = block(guard, f"the guard itself failed ({exc.__class__.__name__}: {exc}).")
    sys.exit(code)
