#!/usr/bin/env python3
"""PreToolUse guard (matcher: Bash): destructive `rm` targets.

Why a hook instead of a `deny` rule: a blanket `Bash(rm -rf:*)` deny blocked
eleven legitimate commands in three weeks (`rm -rf dist` before a build,
throwaway copies from mutation tests) and not a single dangerous one. This
guard allows `rm` on disposable paths and blocks only catastrophic or
unrecoverable targets.

It looks at every command on the line, including those inside `bash -c`, behind
`sudo`/`env`/`xargs` and in subshells (see _shell.py), and understands Windows
paths (`C:\\Users\\name\\project`).

Known limitation: it reads the literal command text. `rm -rf $X`, where $X
expands to a protected path, is not detected. Version control is the safety
net there, not this hook.

Configuration (environment):
  HARNESS_RM_PROTECTED  comma-separated directory names that must never be
                        removed as a whole (default: src,.git,.claude,docs,migrations)
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

from _common import ALLOW, block, command_of, env_list, project_dir, run_guard
from _shell import expand_braces, iter_commands, program_name

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
    "/Volumes",
    "/mnt",
    "/media",
    "/boot",
    "/lib",
    "/lib64",
    "/dev",
    "/proc",
    "/sys",
    "/srv",
    "/usr/local",
    "/private/var",
    "/private/etc",
}
HOME = re.compile(r"^/(Users|home)/[^/]+$")
PARENT_TRAVERSAL = re.compile(r"^\.\.(/\.\.)*$")
ROOT_GLOB = re.compile(r"^/[^/]*[*?\[]")
DOTFILE_GLOB = re.compile(r"^\.(\*|\[!\.\]\*|\?\?\*)$")
# Git Bash (/c/Users) and WSL (/mnt/c/Users) spellings of a Windows drive.
DRIVE_MOUNT = re.compile(r"^/(?:mnt/)?([a-zA-Z])(?=/|$)")
WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
WINDOWS_ROOT = re.compile(r"^[A-Za-z]:/?$")
WINDOWS_HOME = re.compile(r"^[A-Za-z]:/Users/[^/]+$", re.IGNORECASE)
WINDOWS_SYSTEM = re.compile(
    r"^[A-Za-z]:/(windows|users|programdata|program files( \(x86\))?)$", re.IGNORECASE
)


def normalize(path: str) -> str:
    """Forward slashes, no quotes or repeated slashes, and lower case for Windows drive paths."""
    clean = re.sub(r"['\"]", "", path.strip()).replace("\\", "/")
    clean = re.sub(r"/{2,}", "/", clean)
    clean = DRIVE_MOUNT.sub(lambda match: f"{match.group(1)}:", clean)
    if WINDOWS_DRIVE.match(clean):
        clean = clean.lower()
    return posixpath.normpath(clean) if clean else ""


def is_system_path(clean: str) -> bool:
    return clean in SYSTEM_TARGETS or bool(WINDOWS_ROOT.match(clean) or WINDOWS_SYSTEM.match(clean))


def danger_reason(target: str, protected: set[str], project_dir: str) -> str | None:
    clean = normalize(target)
    if not clean:
        return None
    if is_system_path(clean):
        return "is a root, system or wildcard path"
    if PARENT_TRAVERSAL.match(clean) or ROOT_GLOB.match(clean) or DOTFILE_GLOB.match(clean):
        return "is a parent directory or a wildcard over a root"
    if clean.endswith("/*"):
        parent = clean[:-2] or "/"
        if is_system_path(parent) or HOME.match(parent) or WINDOWS_HOME.match(parent):
            return "is the whole content of a root, system or home path"
        if posixpath.basename(parent) in protected:
            return f"is the whole content of a protected folder ({posixpath.basename(parent)})"
    if clean.startswith("~") or re.match(r"^\$\{?HOME\}?", clean):
        return "is inside the user's home directory"
    if HOME.match(clean) or WINDOWS_HOME.match(clean):
        return "is a user's home directory"
    if project_dir and clean == normalize(project_dir):
        return "is the project root"
    name = posixpath.basename(clean)
    if WINDOWS_DRIVE.match(clean):
        protected = {item.lower() for item in protected}
    if name in protected:
        return f"is source code or repository metadata ({name})"
    return None


def rm_targets(tokens: list[str]) -> list[str]:
    if not tokens or program_name(normalize(tokens[0])) != "rm":
        return []
    targets: list[str] = []
    end_of_flags = False
    for arg in tokens[1:]:
        if arg == "--":
            end_of_flags = True
            continue
        if not end_of_flags and arg.startswith("-") and arg != "-":
            continue
        targets.append(arg)
    return targets


def resolve(target: str, cwd: str) -> str:
    """A relative target under the folder a previous `cd` moved to."""
    clean = target.strip("'\"")
    if not cwd or clean.startswith(("/", "~", "$")) or WINDOWS_DRIVE.match(normalize(clean)):
        return target
    return f"{cwd}/{clean}"


def check(event: dict[str, Any]) -> int:
    command = command_of(event)
    protected = set(env_list("HARNESS_RM_PROTECTED", "src,.git,.claude,docs,migrations"))
    root = project_dir(event)
    cwd = ""
    for found in iter_commands(command, windows=True):
        if found.tokens and program_name(normalize(found.tokens[0])) in {"cd", "pushd"}:
            moved = [t for t in found.tokens[1:] if t != "--" and not t.startswith("-")]
            cwd = normalize(resolve(moved[0], cwd)) if moved else ""
        for token in rm_targets(found.tokens):
            for target in expand_braces(token):
                reason = danger_reason(resolve(target, cwd), protected, root)
                if reason:
                    return block(
                        GUARD,
                        f"the target {token!r} {reason}. "
                        "If it really has to go, ask the user to run it themselves.",
                    )
    return ALLOW


if __name__ == "__main__":
    run_guard(GUARD, check)
