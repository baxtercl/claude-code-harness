"""data_guard must see the protected data however the command is written (review of 0.2.0)."""

import os
import time
from pathlib import Path

import pytest
from test_data_guard import bash, decision


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "backups").mkdir()
    return tmp_path


BLOCKED = [
    # The override of one command does not cover the next one.
    "DATABASE_URL=sqlite:////tmp/t.db alembic upgrade head && alembic upgrade head",
    "echo DATABASE_URL=/tmp/x; alembic upgrade head",
    "echo --db /tmp/x; alembic upgrade head",
    # Nested and quoted programs.
    'bash -c "alembic upgrade head"',
    "sh -c 'python apply_draft.py --apply'",
    '"alembic" "upgrade" head',
    "python apply_draft.py --apply=1",
    "sudo -u x alembic upgrade head",
    # sqlite3 options, input and dot-commands.
    "sqlite3 -cmd 'DELETE FROM t' data/app.db",
    "sqlite3 data/app.db < x.sql",
    "sqlite3 data/app.db <<EOF\nDELETE FROM t;\nEOF",
    'sqlite3 data/app.db ".restore /tmp/x"',
    'sqlite3 data/app.db ".import /tmp/x t"',
    "sqlite3 data/app.db \"select writefile('/tmp/x', 'y')\"",
    "sqlite3 'file:data/app.db?mode=rw' 'drop table t'",
    'sqlite3 data/app.db "pragma user_version = 3"',
    # Spellings of the same path, and parents of it.
    "rm data//app.db",
    "rm data/./app.db",
    "rm Data/APP.db",
    "cd data && rm app.db",
    "rm -rf data",
    "rm data/*",
    "rm -rf data/up*",
    "cp -t data/uploads /tmp/x",
    "cp --target-directory=data/uploads /tmp/x",
    "echo x >| data/app.db",
    "install /tmp/x data/app.db",
    "rsync -a /tmp/x data/uploads",
    "ln -sf /tmp/x data/app.db",
    "echo x | tee data/app.db",
    "sed -i s/a/b/ data/app.db",
]

ALLOWED = [
    "sqlite3 -readonly data/app.db < query.sql",
    "sqlite3 -readonly data/app.db '.tables'",
    "rm -rf data/tmp",
    "rm data/other.txt",
    "echo 'alembic upgrade head'",
    "git commit -m 'docs: run alembic upgrade head'",
    "cd data && ls",
    "cd /tmp && rm app.db",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks(command, project):
    result = bash(command, project)
    assert result.returncode == 2, command


@pytest.mark.parametrize("command", ALLOWED)
def test_allows(command, project):
    result = bash(command, project)
    assert result.returncode == 0, result.stderr
    assert decision(result) is None


def test_writes_to_a_lookalike_outside_the_project_are_allowed(project, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    event = {"tool_name": "Write", "tool_input": {"file_path": str(outside / "data" / "app.db")}}
    from test_data_guard import event_run

    assert event_run(event, project).returncode == 0


def test_a_relative_path_is_resolved_from_the_working_directory(project):
    from test_data_guard import event_run

    (project / "data").mkdir()
    event = {
        "tool_name": "Bash",
        "tool_input": {"command": "rm app.db"},
        "cwd": str(project / "data"),
    }
    assert event_run(event, project).returncode == 2


def test_an_empty_file_is_not_a_backup(project):
    (project / "backups" / "fake").write_text("")
    assert bash("python a.py --apply", project).returncode == 2
    (project / "backups" / "empty-dir").mkdir()
    assert bash("python a.py --apply", project).returncode == 2


def test_a_backup_with_content_unlocks_the_apply_flag(project):
    snapshot = project / "backups" / "2026-01-01"
    snapshot.mkdir()
    (snapshot / "app.db").write_text("copy")
    now = time.time()
    os.utime(snapshot / "app.db", (now, now))
    os.utime(snapshot, (now, now))
    assert decision(bash("python a.py --apply", project)) == "ask"


def test_unreadable_command_fails_closed(project):
    result = bash('echo "oops', project)
    assert result.returncode == 2
    assert "the guard itself failed" in result.stderr
