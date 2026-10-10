#!/usr/bin/env python3
"""PreToolUse guard (matcher: Bash): destructive `rm` targets.

Why a hook instead of a `deny` rule: a blanket `Bash(rm -rf:*)` deny blocked
eleven legitimate commands in three weeks (`rm -rf dist` before a build,
throwaway copies from mutation tests) and not a single dangerous one. This
guard allows `rm` on disposable paths and blocks only catastrophic or
unrecoverable targets.

Known limitation: it reads the literal command text. `rm -rf $X`, where $X
expands to a protected path, is not detected. Version control is the safety
net there, not this hook.

Configuration (environment):
  HARNESS_RM_PROTECTED  comma-separated directory names that must never be
                        removed as a whole (default: src,.git,.claude,docs,migrations)
"""

from __future__ import annotations

import os
import re
from typing import Any

from _common import ALLOW, block, command_of, env_list, run_guard, tokenize

GUARD = "rm-guard"

SYSTEM_TARGETS = {
    "",
    "/",
    "*",
    ".",
    "..",
    "./",
    "~",
    "$HOME",
    "${HOME}",
    "$PWD",
    "${PWD}",
    "/Users",
    "/home",
    "/root",
    "/etc",
    "/var",
    "/usr",
    "/opt",
    "/bin",
    "/sbin",
    "/System",
    "/Library",
    "/Applications",
    "/private",
    "/private/tmp",
    "/tmp",
}
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = {"sudo", "time", "nohup", "command", "xargs", "exec", "env"}
SEGMENT_SPLIT = re.compile(r"&&|\|\||[;\n|]")


def danger_reason(target: str, protected: set[str], project_dir: str) -> str | None:
    target = target.strip()
    if not target:
        return None
    clean = target.rstrip("/") or "/"
    if clean in SYSTEM_TARGETS or target in SYSTEM_TARGETS:
        return "is a root, system or wildcard path"
    if clean.startswith("~") or re.match(r"^\$\{?HOME\}?", clean):
        return "is inside the user's home directory"
    if re.match(r"^/(Users|home)/[^/]+$", clean):
        return "is a user's home directory"
    if project_dir and os.path.normpath(clean) == os.path.normpath(project_dir):
        return "is the project root"
    if os.path.basename(clean) in protected:
        return f"is source code or repository metadata ({os.path.basename(clean)})"
    return None


def rm_targets(segment: str) -> list[str]:
    tokens = tokenize(segment)
    i = 0
    while i < len(tokens) and (ENV_ASSIGNMENT.match(tokens[i]) or tokens[i] in WRAPPERS):
        i += 1
    if i >= len(tokens) or os.path.basename(tokens[i]) != "rm":
        return []
    targets: list[str] = []
    end_of_flags = False
    for arg in tokens[i + 1 :]:
        if arg == "--":
            end_of_flags = True
            continue
        if not end_of_flags and arg.startswith("-") and arg != "-":
            continue
        targets.append(arg)
    return targets


def check(event: dict[str, Any]) -> int:
    command = command_of(event)
    if not re.search(r"\brm\b", command):
        return ALLOW
    protected = set(env_list("HARNESS_RM_PROTECTED", "src,.git,.claude,docs,migrations"))
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    for segment in SEGMENT_SPLIT.split(command):
        for target in rm_targets(segment):
            reason = danger_reason(target, protected, project_dir)
            if reason:
                return block(
                    GUARD,
                    f"the target {target!r} {reason}. "
                    "If it really has to go, ask the user to run it themselves.",
                )
    return ALLOW


if __name__ == "__main__":
    run_guard(GUARD, check)
