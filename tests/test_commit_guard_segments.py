"""commit_guard decides per command segment, and reads trailers only on trailer lines."""

import subprocess
import sys

import pytest
from conftest import HOOKS

sys.path.insert(0, str(HOOKS))
from _shell import split_segments  # noqa: E402


@pytest.fixture
def feature_repo(git_repo):
    subprocess.run(["git", "-C", str(git_repo), "checkout", "-q", "-b", "feature/x"], check=True)
    return git_repo


def run(hook, repo, command, env=None):
    return hook("commit_guard.py", command, cwd=str(repo), env=env)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("a && b; c | d", ["a", "b", "c", "d"]),
        ('echo "a; b" && ls', ['echo "a; b"', "ls"]),
        ("echo 'x | y'", ["echo 'x | y'"]),
        ("x=$(one two)", ["x=$", "one two"]),
        ("one\ntwo", ["one", "two"]),
        ("cat <<EOF\nbody; text\nEOF\nnext", ["cat <<EOF", "next"]),
        ("cat <<-'EOF'\n\tbody\n\tEOF\nnext", ["cat <<-'EOF'", "next"]),
        # An unterminated heredoc is not dropped: its lines are inspected as commands.
        ("cat <<EOF\none\ntwo", ["cat <<EOF", "one", "two"]),
        ("echo $((1<<2)); next", ["echo $((1<<2))", "next"]),
        ("echo a\\;b", ["echo a\\;b"]),
    ],
)
def test_split_segments(command, expected):
    assert split_segments(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        'echo "run git commit -m bad"',
        'grep -rn "git commit" docs',
        "git log --grep 'git commit'",
        "cat <<EOF\nrun git commit -m bad\nEOF",
        "git status && echo done",
    ],
)
def test_text_that_mentions_a_commit_is_not_a_commit(hook, git_repo, command):
    result = run(hook, git_repo, command)  # the repository is on main
    assert result.returncode == 0, result.stderr


def test_message_of_another_program_is_not_used(hook, feature_repo):
    command = "python -m pytest -q && git commit -m 'feat: add search'"
    assert run(hook, feature_repo, command).returncode == 0


def test_message_is_taken_from_the_commit_segment(hook, feature_repo):
    result = run(hook, feature_repo, "python -m pytest -q && git commit -m 'oops'")
    assert result.returncode == 2
    assert "Conventional Commit" in result.stderr


def test_every_commit_in_the_command_is_checked(hook, feature_repo):
    result = run(hook, feature_repo, "git commit -m 'feat: a' && git commit -m 'oops'")
    assert result.returncode == 2


def test_chained_commit_on_protected_branch_is_blocked(hook, git_repo):
    result = run(hook, git_repo, "python -m pytest -q && git commit -m 'feat: x'")
    assert result.returncode == 2
    assert "protected" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git commit -am 'oops'",
        "git commit --message='oops'",
        "git commit --message oops",
        "git commit -mfoo",
        "/usr/bin/git commit -m oops",
        "git -c user.name=x commit -m oops",
        "git --no-pager commit -m oops",
        "FOO=1 git commit -m oops",
        "sudo git commit -m oops",
        "echo $(git commit -m oops)",
        "if true; then git commit -m oops; fi",
        "bash -c \"git commit -m 'oops'\"",
        "bash -lc \"git commit -m 'oops'\"",
        "sh -c 'git commit -m oops'",
        "eval \"git commit -m 'oops'\"",
        "bash -c \"bash -c 'git commit -m oops'\"",
    ],
)
def test_detects_commit_forms_and_rejects_bad_message(hook, feature_repo, command):
    result = run(hook, feature_repo, command)
    assert result.returncode == 2, command
    assert "Conventional Commit" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git commit -am 'feat: ok'",
        "git commit -m'feat: ok'",
        "git commit --message='feat: ok'",
        "git commit",
        "git commit --amend --no-edit",
        "git commit -F message.txt",
    ],
)
def test_allows_valid_commit_forms_on_feature_branch(hook, feature_repo, command):
    result = run(hook, feature_repo, command)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "command",
    ["git commit", "git commit -F message.txt", "bash -c 'git commit -m \"feat: x\"'"],
)
def test_protected_branch_is_blocked_even_without_a_message(hook, git_repo, command):
    result = run(hook, git_repo, command)
    assert result.returncode == 2
    assert "protected" in result.stderr


def test_message_given_through_a_heredoc_substitution(hook, feature_repo):
    good = "git commit -m \"$(cat <<'EOF'\nfeat: add search\n\nLonger body.\nEOF\n)\""
    bad = good.replace("feat: add search", "add search")
    assert run(hook, feature_repo, good).returncode == 0
    assert run(hook, feature_repo, bad).returncode == 2


def test_nesting_too_deep_fails_closed(hook, feature_repo):
    command = 'bash -c "bash -c \'bash -c \\"bash -c true\\"\'"'
    result = run(hook, feature_repo, command)
    assert result.returncode == 2
    assert "the guard itself failed" in result.stderr
