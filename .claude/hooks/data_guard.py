#!/usr/bin/env python3
"""PreToolUse guard (matchers: Bash and Write|Edit|MultiEdit|NotebookEdit): live application data.

Opt-in: it does nothing until HARNESS_DATA_PATHS lists what to protect, and it is
not wired in the default settings.json (see the README for the hook entries).

Why it exists: an agent that can run a migration or a data script can destroy data
that version control does not hold (a SQLite file, uploaded documents). This guard
turns "back up before you mutate" into a rule that does not depend on remembering it.

Blocks (exit 2):
  - rm, mv, truncate, dd, shred, unlink or rmdir on a protected path or on a folder
    that contains one (also with a wildcard); cp, install, rsync, ln, tee and `sed -i`
    onto it; a shell redirection onto it;
  - sqlite3 on a protected database with a write statement or a write dot-command, or
    reading its commands from stdin or a file without -readonly;
  - a command matching HARNESS_DATA_BLOCK_PATTERNS (for example `alembic upgrade`);
  - a command with the apply flag (default --apply) and no recent backup;
  - Write/Edit/MultiEdit/NotebookEdit on a protected path.
Asks the user (permissionDecision "ask"):
  - a command matching HARNESS_DATA_ASK_PATTERNS (for example a migration script);
  - a command with the apply flag, once a recent backup exists.

Every command on the line is inspected, including those inside `bash -c` and behind
`sudo`/`env`/`xargs` (see _shell.py). A command counts as targeting the protected data
unless it points elsewhere with an inline DATABASE_URL=..., --database <path> or
--db <path> that is not protected.

Paths are matched by suffix when they are relative and by location when they are absolute
(an absolute path outside the project is not protected), case-insensitively, after
collapsing `.`, `..` and repeated slashes. A `cd` earlier on the line is followed.

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

import fnmatch
import json
import os
import posixpath
import re
import time
from pathlib import Path
from typing import Any

from _common import (
    ALLOW,
    block,
    command_of,
    env_list,
    is_codex,
    patch_paths,
    project_dir as find_project_dir,
    run_guard,
)
from _shell import Command, expand_braces, iter_commands, program_name

GUARD = "data-guard"

# Programs that remove or overwrite every path argument.
REMOVERS = {"rm", "mv", "truncate", "shred", "unlink", "rmdir"}
# Programs that only alter their destination (the last argument, or -t DIR).
COPIERS = {"cp", "install", "rsync", "ln"}
REDIRECT_TOKEN = re.compile(r"^\d?(?:>>?\|?|&>>?)(.*)$")
INPUT_REDIRECT = re.compile(r"^\d?<(?!<)(.*)$")
SQLITE_VALUE_OPTIONS = {"-init", "-separator", "-newline", "-nullvalue", "-vfs", "-mmap", "-key"}
SQL_WRITE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|vacuum|reindex|attach|analyze|begin"
    r"|writefile|load_extension)\b|\bpragma\s+\w+\s*[=(]",
    re.IGNORECASE,
)
DOT_WRITE = re.compile(r"(^|\s)\.(restore|import|read|load|shell|system|output|once|open)\b", re.I)
# Programs whose arguments are text, not commands to run.
TEXT_PROGRAMS = {"echo", "printf", "cat", "grep", "rg", "less", "head", "tail", "man", "which"}
GLOB = re.compile(r"[*?\[]")
FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"}


def normalize(path: str) -> str:
    clean = re.sub(r"['\"]", "", path.strip()).replace("\\", "/")
    clean = re.sub(r"/{2,}", "/", clean)
    return posixpath.normpath(clean) if clean else ""


def is_absolute(path: str) -> bool:
    return path.startswith("/") or bool(re.match(r"^[A-Za-z]:/", path))


def relative_to_project(clean: str, project_dir: str) -> str | None:
    """The path relative to the project; None for an absolute path outside it."""
    if not is_absolute(clean):
        return re.sub(r"^(\./)+", "", clean)
    root = normalize(project_dir).rstrip("/")
    if root and clean.lower() == root.lower():
        return "."
    if root and clean.lower().startswith(root.lower() + "/"):
        return clean[len(root) + 1 :]
    return None if root else clean


def is_protected(
    path: str, project_dir: str, protected: list[str], parents: bool = False, base: str = ""
) -> bool:
    """True for a protected file (and its -wal/-shm/-journal files) or anything under a folder.

    With parents=True, a folder that contains a protected path, or a wildcard that can
    match one, counts too: removing it removes the data.
    """
    clean = normalize(path)
    if not clean:
        return False
    if base and not is_absolute(clean):
        clean = normalize(f"{base}/{clean}")
    relative = relative_to_project(clean, project_dir)
    if relative is None:
        return False
    entries = [normalize(entry).strip("/") for entry in protected]
    if GLOB.search(relative):
        if any(fnmatch.fnmatch(entry.lower(), relative.lower()) for entry in entries):
            return True
        folder = posixpath.dirname(GLOB.split(relative)[0] + "x") or "."
        return parents and any(_contains(folder, entry) for entry in entries)
    for entry in entries:
        pattern = rf"(^|/){re.escape(entry)}(-wal|-shm|-journal)?(/|$)"
        if re.search(pattern, relative, re.IGNORECASE):
            return True
        if parents and _contains(relative, entry):
            return True
    return False


def _contains(folder: str, entry: str) -> bool:
    folder = folder.lower().strip("/")
    return folder in {"", "."} or entry.lower() == folder or entry.lower().startswith(folder + "/")


def database_overrides(raw: list[str]) -> list[str]:
    values = []
    for index, token in enumerate(raw):
        token = token.strip("'\"")
        if token.startswith("DATABASE_URL="):
            values.append(token.split("=", 1)[1])
        elif token in {"--database", "--db"} and index + 1 < len(raw):
            values.append(raw[index + 1])
        elif token.startswith(("--database=", "--db=")):
            values.append(token.split("=", 1)[1])
    return values


def targets_protected_data(found: Command, project_dir: str, protected: list[str]) -> bool:
    """False only when the command explicitly points its database somewhere unprotected."""
    overrides = database_overrides(found.raw)
    if not overrides:
        return True
    return any(is_protected(value, project_dir, protected) for value in overrides)


def normalized_tokens(found: Command) -> list[str]:
    return [token.strip("'\"") for token in found.tokens]


def redirect_targets(raw: list[str]) -> list[str]:
    targets = []
    for index, token in enumerate(raw):
        match = REDIRECT_TOKEN.match(token)
        if not match:
            continue
        if match.group(1):
            targets.append(match.group(1))
        elif index + 1 < len(raw):
            targets.append(raw[index + 1])
    return targets


def has_content(entry: Path) -> bool:
    try:
        if entry.is_file():
            return entry.stat().st_size > 0
        return any(has_content(child) for child in entry.iterdir())
    except OSError:
        return False


def recent_backup(project_dir: str, backup_dir: str, max_age_minutes: float) -> Path | None:
    if not backup_dir:
        return None
    folder = Path(project_dir or ".") / backup_dir
    if not folder.is_dir():
        return None
    entries = [entry for entry in folder.iterdir() if has_content(entry)]
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


def edited_paths(tool_input: dict[str, Any]) -> list[str]:
    """The files a Write/Edit/NotebookEdit call or a Codex apply_patch call changes."""
    direct = (
        tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
    )
    paths = [str(direct)] if direct else []
    patch = tool_input.get("command")
    if isinstance(patch, str):
        paths += patch_paths(patch)
    return paths


def check_file_tool(event: dict[str, Any], root: str, protected: list[str]) -> int:
    for path in edited_paths(event.get("tool_input") or {}):
        if is_protected(path, root, protected):
            return block(
                GUARD,
                f"{path!r} is live application data. Change it through the application, "
                "never by editing the file.",
            )
    return ALLOW


class Scope:
    """What a line of commands has established so far: the folder after a `cd`."""

    def __init__(self, project_dir: str, protected: list[str], cwd: str) -> None:
        self.project_dir = project_dir
        self.protected = protected
        root = normalize(project_dir)
        here = normalize(cwd)
        self.base = ""
        if root and here.lower().startswith(root.lower() + "/"):
            self.base = here[len(root) + 1 :]

    def protects(self, path: str, parents: bool = False) -> bool:
        return is_protected(path, self.project_dir, self.protected, parents, self.base)

    def follow_cd(self, args: list[str]) -> None:
        moved = [arg for arg in args if arg != "--" and not arg.startswith("-")]
        target = normalize(moved[0]) if moved else ""
        if target and is_absolute(target):
            relative = relative_to_project(target, self.project_dir)
            self.base = "" if relative in {None, "."} else relative
        elif target and not target.startswith("~"):
            self.base = normalize(f"{self.base}/{target}") if self.base else target
        else:
            self.base = ""


def path_arguments(program: str, tokens: list[str]) -> tuple[list[str], bool]:
    """The paths a file-altering program changes, and whether a parent folder counts."""
    args = [token for token in tokens[1:] if not token.startswith("-")]
    if program in REMOVERS:
        return args, True
    if program == "dd":
        return [a.removeprefix("of=") for a in tokens[1:] if a.startswith("of=")], False
    if program == "find" and ("-delete" in tokens or "-exec" in tokens):
        roots = []
        for token in tokens[1:]:
            if token.startswith(("-", "(", "!")):
                break
            roots.append(token)
        return roots or ["."], True
    if program == "rsync":
        destination = args[-1:]
        return destination, "--delete" in tokens or any(t.startswith("--delete-") for t in tokens)
    if program in COPIERS:
        for index, token in enumerate(tokens[1:-1], start=1):
            if token in {"-t", "--target-directory"}:
                return [tokens[index + 1]], False
        explicit = [t.split("=", 1)[1] for t in tokens[1:] if t.startswith("--target-directory=")]
        return explicit or args[-1:], False
    if program == "tee":
        return args, False
    if program == "sed" and any(re.match(r"^-\w*i|^--in-place", t) for t in tokens[1:]):
        return args, False
    return [], False


def check_sqlite(found: Command, tokens: list[str], scope: Scope) -> int:
    database = ""
    statements: list[str] = []
    skip = False
    for index, token in enumerate(tokens[1:], start=1):
        if skip:
            skip = False
        elif token == "-cmd" and index + 1 < len(tokens):
            statements.append(tokens[index + 1])
            skip = True
        elif token in SQLITE_VALUE_OPTIONS:
            skip = True
        elif token.startswith("-") or INPUT_REDIRECT.match(token):
            continue
        elif not database:
            database = token
        else:
            statements.append(token)
    database = re.sub(r"\?.*$", "", database.removeprefix("file:"))
    if not database or not scope.protects(database):
        return ALLOW
    sql = " ".join(statements)
    reads_input = bool(found.stdin) or any(INPUT_REDIRECT.match(t) for t in found.raw)
    readonly = "-readonly" in tokens
    if DOT_WRITE.search(sql) or (SQL_WRITE.search(sql) and not readonly):
        reason = "a write statement"
    elif not readonly and (reads_input or not sql):
        reason = "commands read from stdin or a file, or an interactive session"
    else:
        return ALLOW
    return block(
        GUARD,
        f"sqlite3 on the live database with {reason}. "
        "Use -readonly with a SELECT, or a temporary copy.",
    )


def check_redirections(found: Command, scope: Scope) -> int:
    for target in redirect_targets(found.raw):
        if scope.protects(target):
            return block(GUARD, f"the redirection would overwrite live data ({target!r}).")
    return ALLOW


def check_command(found: Command, scope: Scope, asks: list[str]) -> int:
    tokens = normalized_tokens(found)
    if not tokens:  # only assignments and redirections
        return check_redirections(found, scope)
    program = program_name(tokens[0])
    if program in {"cd", "pushd"}:
        scope.follow_cd(tokens[1:])
        return ALLOW

    paths, parents = path_arguments(program, tokens)
    for path in (expanded for token in paths for expanded in expand_braces(token)):
        if scope.protects(path, parents):
            return block(
                GUARD,
                f"{program} on {path!r} would alter live data. "
                f"Ask the user to do it themselves, after a backup. {backup_hint()}.",
            )
    code = check_redirections(found, scope)
    if code != ALLOW:
        return code
    if program == "sqlite3":
        code = check_sqlite(found, tokens, scope)
        if code != ALLOW:
            return code
    live = targets_protected_data(found, scope.project_dir, scope.protected)
    return check_live_commands(tokens, scope.project_dir, live, asks)


def check_live_commands(tokens: list[str], project_dir: str, live: bool, asks: list[str]) -> int:
    if not live or program_name(tokens[0]) in TEXT_PROGRAMS:
        return ALLOW
    # Quoted arguments (with spaces) are text, not command words.
    words = " ".join(token for token in tokens if not re.search(r"\s", token))
    for pattern in env_list("HARNESS_DATA_BLOCK_PATTERNS", ""):
        if re.search(pattern, words):
            return block(
                GUARD,
                f"this command matches {pattern!r} and would change live data without a "
                f"backup. {backup_hint()}, then ask the user to run it.",
            )
    flag = os.environ.get("HARNESS_DATA_APPLY_FLAG", "--apply").strip()
    if flag and any(token == flag or token.startswith(flag + "=") for token in tokens):
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
        if re.search(pattern, words):
            asks.append(f"this command matches {pattern!r} and changes live data. Confirm.")
            return ALLOW
    return ALLOW


def check(event: dict[str, Any]) -> int:
    protected = env_list("HARNESS_DATA_PATHS", "")
    if not protected:
        return ALLOW
    project_dir = find_project_dir(event)
    if event.get("tool_name") in FILE_TOOLS:
        return check_file_tool(event, project_dir, protected)
    command = command_of(event)
    if not command:
        return ALLOW
    scope = Scope(project_dir, protected, str(event.get("cwd") or ""))
    asks: list[str] = []
    for found in iter_commands(command, windows=True):
        code = check_command(found, scope, asks)
        if code != ALLOW:
            return code
    if asks and is_codex(event):
        # Codex has no "ask" decision: stop, and let the user run the command themselves.
        return block(GUARD, " ".join(asks) + " Ask the user to run it themselves.")
    if asks:
        ask(asks)
    return ALLOW


if __name__ == "__main__":
    run_guard(GUARD, check)
