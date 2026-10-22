#!/usr/bin/env python3
"""PreToolUse guard (matchers: Bash and Write|Edit|MultiEdit|NotebookEdit): live application data.

Opt-in: it does nothing until HARNESS_DATA_PATHS lists what to protect, and it is
not wired in the default settings.json (see the README for the hook entries).

Why it exists: an agent that can run a migration or a data script can destroy data
that version control does not hold (a SQLite file, uploaded documents). This guard
turns "back up before you mutate" into a rule that does not depend on remembering it.

Blocks (exit 2):
  - rm, mv, cp (onto it), truncate, dd, shred, unlink or a shell redirection on a
    protected path;
  - sqlite3 on a protected database with a write statement, or interactively without
    -readonly (the statements cannot be inspected);
  - a command matching HARNESS_DATA_BLOCK_PATTERNS (for example `alembic upgrade`);
  - a command with the apply flag (default --apply) and no recent backup;
  - Write/Edit/MultiEdit/NotebookEdit on a protected path.
Asks the user (permissionDecision "ask"):
  - a command matching HARNESS_DATA_ASK_PATTERNS (for example a migration script);
  - a command with the apply flag, once a recent backup exists.

A command counts as targeting the protected data unless it points elsewhere with an
inline DATABASE_URL=..., --database <path> or --db <path> that is not protected.

Known limitation: like the other guards, it reads the literal command text, so a path
hidden in a variable is not detected. Backups are the safety net there.

Configuration (environment; comma-separated lists):
  HARNESS_DATA_PATHS            protected files or folders, relative to the project
  HARNESS_DATA_BACKUP_DIR       folder where backups land (a recent entry unlocks the apply flag)
  HARNESS_DATA_BACKUP_CMD       backup command quoted in the messages
  HARNESS_BACKUP_MAX_AGE_MINUTES  how recent a backup must be (default 60)
  HARNESS_DATA_APPLY_FLAG       default "--apply"
  HARNESS_DATA_BLOCK_PATTERNS   regular expressions of commands that are always blocked
  HARNESS_DATA_ASK_PATTERNS     regular expressions of commands that need confirmation
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from _common import ALLOW, block, command_of, env_list, run_guard, split_segments, tokenize

GUARD = "data-guard"

DESTRUCTIVE = {"rm", "mv", "cp", "truncate", "dd", "shred", "unlink", "rmdir"}
WRAPPERS = {"sudo", "time", "nohup", "command", "xargs", "exec", "env"}
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
REDIRECT_TOKEN = re.compile(r"^\d?>{1,2}(.*)$")
DATABASE_OVERRIDE = re.compile(r"(?:\bDATABASE_URL=|--database[= ]\s*|--db[= ]\s*)(\S+)")
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
SQL_WRITE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|vacuum|reindex|attach|pragma\s+\w+\s*=)\b",
    re.IGNORECASE,
)
FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def normalize(path: str) -> str:
    return path.strip().strip("'\"").replace("\\", "/")


def is_protected(path: str, project_dir: str, protected: list[str]) -> bool:
    """True for a protected file (and its -wal/-shm/-journal files) or anything under a folder."""
    clean = normalize(path)
    if not clean:
        return False
    root = normalize(project_dir).rstrip("/")
    if root and clean.startswith(root + "/"):
        clean = clean[len(root) + 1 :]
    clean = re.sub(r"^(\./)+", "", clean).rstrip("/")
    for entry in protected:
        pattern = rf"(^|/){re.escape(normalize(entry).strip('/'))}(-wal|-shm|-journal)?(/|$)"
        if re.search(pattern, clean):
            return True
    return False


def targets_protected_data(command: str, project_dir: str, protected: list[str]) -> bool:
    """False only when the command explicitly points its database somewhere unprotected."""
    overrides = DATABASE_OVERRIDE.findall(command)
    if not overrides:
        return True
    return any(is_protected(value, project_dir, protected) for value in overrides)


def command_tokens(segment: str) -> list[str]:
    # Non-POSIX splitting keeps Windows backslashes; normalize() strips the quotes.
    tokens = [normalize(token) for token in tokenize(segment, posix=False)]
    index = 0
    while index < len(tokens) and (
        ENV_ASSIGNMENT.match(tokens[index]) or tokens[index] in WRAPPERS
    ):
        index += 1
    return tokens[index:]


def redirect_targets(tokens: list[str]) -> list[str]:
    targets = []
    for index, token in enumerate(tokens):
        match = REDIRECT_TOKEN.match(token)
        if not match:
            continue
        if match.group(1):
            targets.append(match.group(1))
        elif index + 1 < len(tokens):
            targets.append(tokens[index + 1])
    return targets


def recent_backup(project_dir: str, backup_dir: str, max_age_minutes: float) -> Path | None:
    if not backup_dir:
        return None
    folder = Path(project_dir or ".") / backup_dir
    if not folder.is_dir():
        return None
    entries = [entry for entry in folder.iterdir() if entry.is_file() or any(entry.iterdir())]
    if not entries:
        return None
    newest = max(entries, key=lambda entry: entry.stat().st_mtime)
    fresh = time.time() - newest.stat().st_mtime <= max_age_minutes * 60
    return newest if fresh else None


def ask(reasons: list[str]) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": f"{GUARD}: {' '.join(reasons)}",
                }
            }
        )
    )


def backup_hint() -> str:
    command = os.environ.get("HARNESS_DATA_BACKUP_CMD", "").strip()
    return f"Run '{command}' first" if command else "Take a backup first"


def check_file_tool(event: dict[str, Any], project_dir: str, protected: list[str]) -> int:
    tool_input = event.get("tool_input") or {}
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if is_protected(path, project_dir, protected):
        return block(
            GUARD,
            f"{path!r} is live application data. Change it through the application, "
            "never by editing the file.",
        )
    return ALLOW


def check_segment(
    segment: str, project_dir: str, protected: list[str], live: bool, asks: list[str]
) -> int:
    tokens = command_tokens(segment)
    if not tokens:
        return ALLOW
    program = os.path.basename(tokens[0])
    args = [arg for arg in tokens[1:] if not arg.startswith("-")]

    if program in DESTRUCTIVE:
        # cp only alters its destination; reading protected data into a copy is fine.
        touched = args[-1:] if program == "cp" else args
        for arg in touched:
            candidate = arg.removeprefix("of=") if program == "dd" else arg
            if is_protected(candidate, project_dir, protected):
                return block(
                    GUARD,
                    f"{program} on {arg!r} would alter live data. "
                    f"Ask the user to do it themselves, after a backup. {backup_hint()}.",
                )
    for target in redirect_targets(tokens):
        if is_protected(target, project_dir, protected):
            return block(GUARD, f"the redirection would overwrite live data ({target!r}).")
    if program == "sqlite3" and args and is_protected(args[0], project_dir, protected):
        sql = " ".join(args[1:])
        if SQL_WRITE.search(sql) or (not sql and "-readonly" not in tokens):
            return block(
                GUARD,
                "sqlite3 would write to the live database. "
                "Use -readonly with a SELECT, or a temporary copy.",
            )
    return check_live_commands(segment, tokens, project_dir, live, asks)


def check_live_commands(
    segment: str, tokens: list[str], project_dir: str, live: bool, asks: list[str]
) -> int:
    if not live:
        return ALLOW
    unquoted = QUOTED.sub(" ", segment)
    for pattern in env_list("HARNESS_DATA_BLOCK_PATTERNS", ""):
        if re.search(pattern, unquoted):
            return block(
                GUARD,
                f"this command matches {pattern!r} and would change live data without a "
                f"backup. {backup_hint()}, then ask the user to run it.",
            )
    flag = os.environ.get("HARNESS_DATA_APPLY_FLAG", "--apply").strip()
    if flag and flag in tokens:
        max_age = float(os.environ.get("HARNESS_BACKUP_MAX_AGE_MINUTES") or 60)
        backup_dir = os.environ.get("HARNESS_DATA_BACKUP_DIR", "").strip()
        backup = recent_backup(project_dir, backup_dir, max_age)
        if backup is None:
            return block(
                GUARD,
                f"{flag} mutates live data and there is no backup newer than "
                f"{max_age:g} minutes. {backup_hint()} (with the user's approval).",
            )
        asks.append(
            f"{flag} will mutate live data. Latest backup: {backup}. Confirm with the user."
        )
        return ALLOW
    for pattern in env_list("HARNESS_DATA_ASK_PATTERNS", ""):
        if re.search(pattern, unquoted):
            asks.append(f"this command matches {pattern!r} and changes live data. Confirm.")
            return ALLOW
    return ALLOW


def check(event: dict[str, Any]) -> int:
    protected = env_list("HARNESS_DATA_PATHS", "")
    if not protected:
        return ALLOW
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or str(event.get("cwd") or "")
    if event.get("tool_name") in FILE_TOOLS:
        return check_file_tool(event, project_dir, protected)
    command = command_of(event)
    if not command:
        return ALLOW
    live = targets_protected_data(command, project_dir, protected)
    asks: list[str] = []
    for segment in split_segments(command):
        code = check_segment(segment, project_dir, protected, live, asks)
        if code != ALLOW:
            return code
    if asks:
        ask(asks)
    return ALLOW


if __name__ == "__main__":
    run_guard(GUARD, check)
