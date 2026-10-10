#!/usr/bin/env python3
"""Print a .env file with secret values redacted.

The sanctioned way for an agent (or a human sharing a screen) to answer
"which flags are on and which database does this environment point to?"
without a secret ever reaching a transcript.

Kept as-is: booleans, numbers, and the scheme/host/port/path of URLs.
Redacted: everything else, plus credentials embedded in URLs.

Usage: python3 tools/env_inspect.py [path/to/.env]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SAFE_LITERAL = re.compile(r"^(true|false|yes|no|on|off|\d+(\.\d+)?)$", re.IGNORECASE)


def redact_url(value: str) -> str | None:
    parts = urlsplit(value)
    if not parts.scheme or not parts.hostname:
        return None
    netloc = parts.hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    if parts.username:
        netloc = f"{parts.username}:***@{netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def redact(value: str) -> str:
    value = value.strip().strip("'\"")
    if not value:
        return ""
    if SAFE_LITERAL.match(value):
        return value
    url = redact_url(value)
    if url is not None:
        return url
    return f"***REDACTED*** ({len(value)} chars)"


def inspect(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        lines.append(f"{key}={redact(value)}")
    return lines


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else ".env")
    if not path.is_file():
        sys.stderr.write(f"{path}: not found\n")
        return 1
    print("\n".join(inspect(path.read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
