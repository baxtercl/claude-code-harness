#!/usr/bin/env python3
"""PreToolUse guard (matcher: Bash): files that hold secrets.

Why a hook on top of `deny` rules: `Read(...)` deny globs turned out to be
inconsistent in practice (some patterns blocked, close variants did not), and
they only cover the Read tool, not `cat .env` through Bash. Here the criteria
are explicit and tested.

Deliberately exempt: `.env.example`, `.env.sample` and `.env.template`, which
are tracked and hold no real values. Blocking them used to stop dozens of
legitimate commands. To look at a real `.env` without leaking values, use
`tools/env_inspect.py`, which redacts secrets.
"""

from __future__ import annotations

import re
from typing import Any

from _common import ALLOW, block, command_of, run_guard

GUARD = "secret-file-guard"

QUICK_FILTER = re.compile(
    r"\.env|\.pem|\.key|\.p12|\.pfx|service-account|credentials\.json|id_rsa|id_ed25519"
)
EXEMPT = re.compile(r"(^|/)\.env\.(example|sample|template)$")
PROTECTED = re.compile(
    r"(^|/)\.env$"
    r"|(^|/)\.env\.[A-Za-z0-9_.\-]*local$"
    r"|(^|/)\.env\.(production|development|staging|test)$"
    r"|(^|/)\.env\.bak[A-Za-z0-9_.\-]*$"
    r"|\.pem$|\.key$|\.p12$|\.pfx$"
    r"|(^|/)service-account[A-Za-z0-9_.\-]*\.json$"
    r"|[A-Za-z0-9_.\-]*credentials\.json$"
    r"|(^|/)id_rsa$|(^|/)id_ed25519$"
)
SANCTIONED_INSPECTOR = re.compile(r"(^|[\s/])env_inspect\.py\b")

# Quoted literals that contain spaces are prose ("check the .env file"), not
# paths. A quoted path ("$HOME/.env") has no spaces and survives this step.
PROSE_SINGLE = re.compile(r"'[^']*\s[^']*'")
PROSE_DOUBLE = re.compile(r'"[^"]*\s[^"]*"')
TOKEN_SPLIT = re.compile(r"""[\s;|&<>()'"=]+""")


def check(event: dict[str, Any]) -> int:
    command = command_of(event)
    if not QUICK_FILTER.search(command):
        return ALLOW
    if SANCTIONED_INSPECTOR.search(command):
        return ALLOW
    stripped = PROSE_DOUBLE.sub(" ", PROSE_SINGLE.sub(" ", command))
    for token in TOKEN_SPLIT.split(stripped):
        token = token.strip().rstrip(",:")
        if not token or EXEMPT.search(token):
            continue
        if PROTECTED.search(token):
            return block(
                GUARD,
                f"the command touches {token!r}, which holds secrets. "
                "To inspect a .env without exposing values: python3 tools/env_inspect.py <file>",
            )
    return ALLOW


if __name__ == "__main__":
    run_guard(GUARD, check)
