from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / ".claude" / "hooks"


def run_hook(name: str, command: str, cwd: str = "", env: dict[str, str] | None = None):
    event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_")}
    full_env.pop("CLAUDE_PROJECT_DIR", None)
    full_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


@pytest.fixture
def hook():
    return run_hook


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("commit", "-q", "--allow-empty", "-m", "chore: init")
    return tmp_path
