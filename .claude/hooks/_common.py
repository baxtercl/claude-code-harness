"""Shared helpers for the PreToolUse guard hooks.

Claude Code only blocks a tool call when a hook exits with code 2. Any other
non-zero code (for example, an unhandled exception) lets the command through.
For a guard that is the wrong failure mode, so every hook here runs inside
`run_guard`, which turns unexpected errors into a block: guards fail closed.
"""

from __future__ import annotations

import json
import os
import shlex
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
    return str(tool_input.get("command") or "")


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
