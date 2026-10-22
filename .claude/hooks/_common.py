"""Shared helpers for the PreToolUse guard hooks.

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


def tokenize(segment: str, posix: bool = True) -> list[str]:
    """Split a shell segment into tokens; fall back to whitespace on bad quoting.

    posix=False keeps backslashes (Windows paths) and leaves the quotes on the tokens.
    """
    try:
        return shlex.split(segment, posix=posix)
    except ValueError:
        return segment.split()


HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_]\w*)\2")
SEPARATORS = ";&|()`"


def _skip_heredocs(command: str, start: int, pending: list[tuple[str, bool]]) -> int:
    """Index after the bodies of the pending heredocs; `start` if a terminator is missing."""
    index = start
    for delimiter, strip_tabs in pending:
        while True:
            if index >= len(command):
                return start
            end = command.find("\n", index)
            line = command[index:] if end == -1 else command[index:end]
            index = len(command) if end == -1 else end + 1
            line = line.rstrip("\r")
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                break
    return index


def split_segments(command: str) -> list[str]:
    """Split a shell command into simple-command segments.

    `;`, `&`, `|`, newlines, parentheses and backticks separate segments, but only
    outside quotes, so a quoted command name stays inside its argument. Heredoc
    bodies are dropped: they are data, not commands.
    """
    segments: list[str] = []
    current: list[str] = []
    pending: list[tuple[str, bool]] = []
    quote = ""
    index = 0

    def flush() -> None:
        text = "".join(current).strip()
        if text:
            segments.append(text)
        current.clear()

    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command):
            current.append(command[index : index + 2])
            index += 2
        elif quote:
            current.append(char)
            quote = "" if char == quote else quote
            index += 1
        elif char in "'\"":
            quote = char
            current.append(char)
            index += 1
        elif command.startswith("<<", index) and not command.startswith("<<<", index):
            match = HEREDOC.match(command, index)
            if match:
                pending.append((match.group(3), bool(match.group(1))))
                current.append(match.group(0))
                index = match.end()
            else:
                current.append("<<")
                index += 2
        elif char == "\n":
            flush()
            index = _skip_heredocs(command, index + 1, pending)
            pending = []
        elif char in SEPARATORS:
            flush()
            index += 1
        else:
            current.append(char)
            index += 1
    flush()
    return segments


def block(guard: str, reason: str) -> int:
    sys.stderr.write(f"BLOCKED ({guard}): {reason}\n")
    return BLOCK


def run_guard(guard: str, check: Callable[[dict[str, Any]], int]) -> None:
    try:
        code = check(read_event())
    except Exception as exc:  # noqa: BLE001 - fail closed: a crashing guard must not allow
        code = block(guard, f"the guard itself failed ({exc.__class__.__name__}: {exc}).")
    sys.exit(code)
