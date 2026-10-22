import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import HOOKS

CONFIG = {
    "HARNESS_DATA_PATHS": "data/app.db,data/uploads,backups",
    "HARNESS_DATA_BACKUP_DIR": "backups",
    "HARNESS_DATA_BACKUP_CMD": "make backup",
    "HARNESS_DATA_BLOCK_PATTERNS": r"\balembic\b.*\b(upgrade|downgrade|stamp)\b",
    "HARNESS_DATA_ASK_PATTERNS": r"scripts[/\\]migrate\.py",
}

BLOCKED = [
    "rm data/app.db",
    "rm -f data/app.db-wal",
    "rm -rf data/uploads",
    "rm -rf ./backups/",
    "mv data/app.db /tmp/old.db",
    "cp /tmp/other.db data/app.db",
    "truncate -s 0 data/app.db",
    "dd if=/dev/zero of=data/app.db",
    "echo '' > data/app.db",
    "cat dump.sql >> data/app.db",
    "sqlite3 data/app.db 'DELETE FROM users'",
    "sqlite3 data/app.db \"update users set role='ADMIN'\"",
    "sqlite3 data/app.db",
    "alembic upgrade head",
    "cd backend && ../.venv/bin/python -m alembic upgrade head",
    "alembic -c backend/alembic.ini downgrade -1",
    "DATABASE_URL=sqlite:///data/app.db alembic upgrade head",
    "rm data\\uploads\\logo.png",
    "true && rm -rf data/uploads",
]

ALLOWED = [
    "cp data/app.db /tmp/copy.db",
    "sqlite3 -readonly data/app.db 'SELECT count(*) FROM users'",
    "sqlite3 data/app.db 'SELECT count(*) FROM users'",
    "sqlite3 /tmp/copy.db 'DELETE FROM users'",
    "rm -rf data/tmp",
    "rm data/app.db.notes.txt",
    "DATABASE_URL=sqlite:////tmp/x.db alembic upgrade head",
    "python -m pytest tests -q",
    "ls -la backups",
    "echo 'rm data/app.db' is dangerous",
    "git commit -m 'docs: explain --apply and alembic upgrade head'",
    "python scripts/other.py --apply --database /tmp/scratch.db",
    "echo done > /tmp/out.txt",
]


def event_run(event: dict, project: Path | None = None, env: dict[str, str] | None = None):
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_")}
    full_env.pop("CLAUDE_PROJECT_DIR", None)
    full_env.update(CONFIG)
    if project is not None:
        full_env["CLAUDE_PROJECT_DIR"] = str(project)
    full_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(HOOKS / "data_guard.py")],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def bash(command: str, project: Path | None = None, env: dict[str, str] | None = None):
    event = {"tool_name": "Bash", "tool_input": {"command": command}}
    return event_run(event, project, env)


def decision(result) -> str | None:
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "backups").mkdir()
    return tmp_path


def make_backup(project: Path, age_minutes: float) -> Path:
    snapshot = project / "backups" / "2026-01-01"
    snapshot.mkdir()
    (snapshot / "app.db").write_text("copy")
    stamp = time.time() - age_minutes * 60
    os.utime(snapshot / "app.db", (stamp, stamp))
    os.utime(snapshot, (stamp, stamp))
    return snapshot


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_mutations_of_live_data(command, project):
    result = bash(command, project)
    assert result.returncode == 2, command
    assert "data-guard" in result.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_reads_copies_and_unrelated_commands(command, project):
    result = bash(command, project)
    assert result.returncode == 0, result.stderr
    assert decision(result) is None


def test_is_inactive_without_configuration(project):
    result = bash("rm -rf data/uploads", project, env={"HARNESS_DATA_PATHS": ""})
    assert result.returncode == 0
    assert result.stdout == ""


def test_absolute_path_inside_the_project_is_blocked(project):
    assert bash(f"rm {project}/data/app.db", project).returncode == 2


def test_paths_match_by_suffix_so_a_lookalike_elsewhere_is_blocked_too(project, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    assert bash(f"rm {elsewhere}/data/uploads", project).returncode == 2
    assert bash(f"rm {elsewhere}/data/other", project).returncode == 0


def test_migration_script_asks(project):
    result = bash("python scripts/migrate.py", project)
    assert result.returncode == 0
    assert decision(result) == "ask"


def test_migration_script_on_another_database_is_not_guarded(project):
    result = bash("python scripts/migrate.py --database /tmp/scratch.db", project)
    assert decision(result) is None


def test_apply_requires_a_recent_backup_then_asks(project):
    blocked = bash("python scripts/fix.py --apply", project)
    assert blocked.returncode == 2
    assert "make backup" in blocked.stderr

    make_backup(project, age_minutes=5)
    asked = bash("python scripts/fix.py --apply", project)
    assert asked.returncode == 0
    assert decision(asked) == "ask"
    assert "2026-01-01" in asked.stdout


def test_stale_backup_does_not_unlock_apply(project):
    make_backup(project, age_minutes=120)
    assert bash("python scripts/fix.py --apply", project).returncode == 2


def test_backup_age_is_configurable(project):
    make_backup(project, age_minutes=120)
    result = bash(
        "python scripts/fix.py --apply", project, env={"HARNESS_BACKUP_MAX_AGE_MINUTES": "180"}
    )
    assert decision(result) == "ask"


def test_apply_flag_is_configurable(project):
    env = {"HARNESS_DATA_APPLY_FLAG": "--commit"}
    assert bash("python scripts/fix.py --commit", project, env=env).returncode == 2
    assert bash("python scripts/fix.py --apply", project, env=env).returncode == 0


def test_apply_on_another_database_is_not_guarded(project):
    result = bash("python scripts/fix.py --apply --db /tmp/scratch.db", project)
    assert result.returncode == 0
    assert decision(result) is None


def test_several_asks_print_a_single_decision(project):
    make_backup(project, age_minutes=1)
    result = bash("python scripts/migrate.py && python scripts/fix.py --apply", project)
    assert len(result.stdout.strip().splitlines()) == 1
    assert decision(result) == "ask"


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
def test_file_tools_cannot_edit_live_data(tool, project):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    event = {"tool_name": tool, "tool_input": {key: str(project / "data" / "app.db")}}
    assert event_run(event, project).returncode == 2


def test_file_tools_can_edit_other_files(project):
    event = {"tool_name": "Write", "tool_input": {"file_path": str(project / "src" / "app.py")}}
    assert event_run(event, project).returncode == 0


def test_malformed_input_blocks_instead_of_allowing():
    result = subprocess.run(
        [sys.executable, str(HOOKS / "data_guard.py")],
        input="{not json",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "the guard itself failed" in result.stderr
