"""The guards also run under Codex: same JSON on stdin and exit code 2, with three differences.

Codex adds `turn_id`, sets no CLAUDE_PROJECT_DIR, has no "ask" decision and edits files with
`apply_patch`. These tests send Codex-shaped events; `.codex/hooks.json` was also verified
against a real Codex session (see the README).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import HOOKS, ROOT

CONFIG = {
    "HARNESS_DATA_PATHS": "data/app.db,data/uploads",
    "HARNESS_DATA_ASK_PATTERNS": r"scripts/migrate\.py",
}


def codex_event(tool_name, tool_input, cwd):
    return {
        "session_id": "s",
        "turn_id": "t",
        "transcript_path": None,
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "model": "gpt",
        "permission_mode": "default",
        "tool_name": tool_name,
        "tool_use_id": "u",
        "tool_input": tool_input,
    }


def run(guard, event, env=None):
    full_env = {k: v for k, v in os.environ.items() if not k.startswith(("HARNESS_", "CLAUDE_"))}
    full_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(HOOKS / guard)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


@pytest.fixture
def repo(git_repo: Path) -> Path:
    (git_repo / "data").mkdir()
    (git_repo / "sub").mkdir()
    return git_repo


def test_commit_on_a_protected_branch_is_blocked(repo):
    event = codex_event("Bash", {"command": "git commit -m 'feat: x'"}, repo)
    result = run("commit_guard.py", event)
    assert result.returncode == 2
    assert "protected" in result.stderr


def test_command_given_as_an_argv_array_is_inspected(repo):
    event = codex_event("Bash", {"command": ["bash", "-lc", "git commit -m 'feat: x'"]}, repo)
    assert run("commit_guard.py", event).returncode == 2


def test_rm_guard_finds_the_project_root_without_claude_project_dir(repo):
    event = codex_event("Bash", {"command": f'rm -rf "{repo}"'}, repo / "sub")
    result = run("rm_guard.py", event)
    assert result.returncode == 2
    assert "project root" in result.stderr


def test_harness_project_dir_overrides_the_git_root(repo, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    event = codex_event("Bash", {"command": f'rm -rf "{other}"'}, repo)
    assert run("rm_guard.py", event, {"HARNESS_PROJECT_DIR": str(other)}).returncode == 2


@pytest.mark.parametrize(
    "patch",
    [
        "*** Begin Patch\n*** Add File: data/app.db\n+hello\n*** End Patch",
        "*** Begin Patch\n*** Update File: data/app.db\n@@\n-a\n+b\n*** End Patch",
        "*** Begin Patch\n*** Delete File: data/app.db\n*** End Patch",
        "*** Begin Patch\n*** Update File: a.md\n*** Move to: data/uploads/a.md\n*** End Patch",
    ],
)
def test_apply_patch_on_protected_data_is_blocked(repo, patch):
    event = codex_event("apply_patch", {"command": patch}, repo / "sub")
    result = run("data_guard.py", event, CONFIG)
    assert result.returncode == 2, patch
    assert "live application data" in result.stderr


def test_apply_patch_on_other_files_is_allowed(repo):
    patch = "*** Begin Patch\n*** Add File: src/new.py\n+x = 1\n*** End Patch"
    event = codex_event("apply_patch", {"command": patch}, repo)
    assert run("data_guard.py", event, CONFIG).returncode == 0


def test_an_ask_becomes_a_block_because_codex_cannot_ask(repo):
    event = codex_event("Bash", {"command": "python scripts/migrate.py"}, repo)
    result = run("data_guard.py", event, CONFIG)
    assert result.returncode == 2
    assert "Ask the user to run it themselves" in result.stderr
    assert result.stdout == ""


def test_the_same_ask_stays_an_ask_for_claude_code(repo):
    event = codex_event("Bash", {"command": "python scripts/migrate.py"}, repo)
    del event["turn_id"]
    result = run("data_guard.py", event, CONFIG)
    assert result.returncode == 0
    decision = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
    assert decision == "ask"


def commands_by_matcher(config):
    found = {}
    for entry in config["hooks"]["PreToolUse"]:
        found[entry["matcher"]] = [
            Path(hook["command"].split("/")[-1].strip('"')).name for hook in entry["hooks"]
        ]
    return found


def test_codex_hooks_json_wires_the_same_bash_guards_as_claude_settings():
    codex = json.loads((ROOT / ".codex" / "hooks.json").read_text())
    claude = json.loads((ROOT / ".claude" / "settings.json").read_text())
    assert commands_by_matcher(codex)["Bash"] == commands_by_matcher(claude)["Bash"]
    for scripts in commands_by_matcher(codex).values():
        assert all((HOOKS / name).is_file() for name in scripts)


def test_patch_paths_are_relative_to_the_session_directory(repo):
    add = "*** Begin Patch\n*** Add File: {}\n+x\n*** End Patch"
    inside_data = codex_event("apply_patch", {"command": add.format("app.db")}, repo / "data")
    assert run("data_guard.py", inside_data, CONFIG).returncode == 2
    (repo / "data" / "uploads").mkdir()
    inside_uploads = codex_event(
        "apply_patch", {"command": add.format("a.txt")}, repo / "data/uploads"
    )
    assert run("data_guard.py", inside_uploads, CONFIG).returncode == 2
    # Relative paths match by suffix, so sub/data/app.db counts as protected too (on purpose).
    nested = codex_event("apply_patch", {"command": add.format("data/app.db")}, repo / "sub")
    assert run("data_guard.py", nested, CONFIG).returncode == 2
    unrelated = codex_event("apply_patch", {"command": add.format("other.db")}, repo / "sub")
    assert run("data_guard.py", unrelated, CONFIG).returncode == 0


@pytest.mark.parametrize("indent", ["  ", "\t", "    "])
def test_indented_patch_headers_are_read(repo, indent):
    patch = f"*** Begin Patch\n{indent}*** Add File: data/app.db\n+x\n*** End Patch"
    event = codex_event("apply_patch", {"command": patch}, repo)
    assert run("data_guard.py", event, CONFIG).returncode == 2


def test_a_patch_applied_from_the_shell_is_found(repo):
    patch = "*** Begin Patch\\n*** Add File: data/app.db\\n+hi\\n*** End Patch\\n"
    command = f"printf '{patch}' | apply_patch"
    result = run("data_guard.py", codex_event("Bash", {"command": command}, repo), CONFIG)
    assert result.returncode == 2
    heredoc = (
        "apply_patch <<'EOF'\n*** Begin Patch\n*** Update File: data/app.db\n*** End Patch\nEOF"
    )
    assert (
        run("data_guard.py", codex_event("Bash", {"command": heredoc}, repo), CONFIG).returncode
        == 2
    )
    other = "apply_patch <<'EOF'\n*** Begin Patch\n*** Add File: src/x.py\n+x\n*** End Patch\nEOF"
    assert (
        run("data_guard.py", codex_event("Bash", {"command": other}, repo), CONFIG).returncode == 0
    )


def test_a_claude_project_dir_leaked_into_codex_is_ignored(repo, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    event = codex_event("Bash", {"command": f'rm -rf "{repo}"'}, repo)
    assert run("rm_guard.py", event, {"CLAUDE_PROJECT_DIR": str(other)}).returncode == 2
    # Claude Code still trusts its own variable.
    del event["turn_id"]
    assert run("rm_guard.py", event, {"CLAUDE_PROJECT_DIR": str(other)}).returncode == 0


def test_a_missing_git_does_not_break_the_guards(repo):
    event = codex_event("Bash", {"command": "ls"}, repo)
    for guard in ("rm_guard.py", "data_guard.py"):
        assert run(guard, event, {**CONFIG, "PATH": "/nonexistent"}).returncode == 0
