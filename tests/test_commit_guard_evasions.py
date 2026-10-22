"""A real commit must be seen however the command line wraps it (found in review of 0.2.0)."""

import pytest

AI_ENV = {"HARNESS_BLOCK_AI_TRAILERS": "1"}
COMMIT = 'git commit -m "feat: x"'

WRAPPED = [
    f"env -i {COMMIT}",
    f"sudo -u root {COMMIT}",
    f"time -p {COMMIT}",
    f"nice -n 5 {COMMIT}",
    f"timeout 5 {COMMIT}",
    f"command -p {COMMIT}",
    f"nohup {COMMIT}",
    f"xargs -n1 {COMMIT}",
    f">/dev/null {COMMIT}",
    f"2>/dev/null {COMMIT}",
    f"{{ {COMMIT}; }}",
    f"find . -maxdepth 0 -exec {COMMIT} \\;",
    f"FOO=1 BAR=2 {COMMIT}",
]

NESTED = [
    f"bash <<EOF\n{COMMIT}\nEOF",
    f"bash -s <<'EOF'\n{COMMIT}\nEOF",
    f"bash <<< '{COMMIT}'",
    f"echo '{COMMIT}' | sh",
    f"source <(echo '{COMMIT}')",
    f'echo "$({COMMIT})"',
    f"echo `{COMMIT}`",
    f"cat <<EOF | sh\n{COMMIT}\nEOF",
    f"{COMMIT} && echo done",
    "git commit -F - <<EOF && echo done\nfeat: x\nEOF",
]

HIDDEN_BY_SYNTAX = [
    f"echo hi # don't\n{COMMIT}",
    f'echo hi # "\n{COMMIT}',
    f"echo hi # <<E\n{COMMIT}\nE",
    f"echo $((1<<N))\n{COMMIT}\nN",
    f"echo '#'; {COMMIT}",
]


def test_eval_of_a_substitution_is_blocked_even_if_it_cannot_be_parsed(hook, git_repo):
    command = f"eval \"$(echo '{COMMIT}')\""
    assert hook("commit_guard.py", command, cwd=str(git_repo)).returncode == 2


@pytest.mark.parametrize("command", [*WRAPPED, *NESTED, *HIDDEN_BY_SYNTAX])
def test_commit_on_a_protected_branch_is_found(hook, git_repo, command):
    result = hook("commit_guard.py", command, cwd=str(git_repo))
    assert result.returncode == 2, command
    assert "protected" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "echo hi # git commit -m oops",
        'echo "$(date)" "$((1<<2))"',
        "echo `date`",
        "echo '#' && git status",
        "bash -c 'echo hello'",
        "bash scripts/build.sh",
        "sudo ls /root",
        "find . -name '*.py' -exec grep -l commit {} \\;",
    ],
)
def test_commands_that_are_not_commits_pass(hook, git_repo, command):
    result = hook("commit_guard.py", command, cwd=str(git_repo))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("command", ['echo "unterminated', "echo 'unterminated", 'echo "$(date'])
def test_unreadable_command_fails_closed(hook, git_repo, command):
    result = hook("commit_guard.py", command, cwd=str(git_repo))
    assert result.returncode == 2
    assert "the guard itself failed" in result.stderr


def test_wrapped_commit_message_is_still_checked(hook, git_repo):
    import subprocess

    subprocess.run(["git", "-C", str(git_repo), "checkout", "-q", "-b", "feature/x"], check=True)
    result = hook("commit_guard.py", "sudo -u root git commit -m oops", cwd=str(git_repo))
    assert result.returncode == 2
    assert "Conventional Commit" in result.stderr


@pytest.fixture
def feature_repo(git_repo):
    import subprocess

    subprocess.run(["git", "-C", str(git_repo), "checkout", "-q", "-b", "feature/x"], check=True)
    return git_repo


ATTRIBUTION = "Co-Authored-By: Claude <noreply@anthropic.com>"


@pytest.mark.parametrize(
    "command",
    [
        f"git commit -F - <<'EOF'\nfeat: x\n\n{ATTRIBUTION}\nEOF",
        f'git commit -m "feat: x" --trailer "{ATTRIBUTION}"',
        f'git commit -m "feat: x" --trailer="{ATTRIBUTION}"',
        "git commit -m 'feat: x' -m 'Made with Claude Code'",
        f'git commit -F - <<< "feat: x\n\n{ATTRIBUTION}"',
    ],
)
def test_attribution_hidden_in_other_message_sources_is_blocked(hook, feature_repo, command):
    result = hook("commit_guard.py", command, cwd=str(feature_repo), env=AI_ENV)
    assert result.returncode == 2, command
    assert "AI attribution" in result.stderr


def test_attribution_in_a_message_file_is_blocked(hook, feature_repo):
    (feature_repo / "message.txt").write_text(f"feat: x\n\n{ATTRIBUTION}\n")
    result = hook("commit_guard.py", "git commit -F message.txt", cwd=str(feature_repo), env=AI_ENV)
    assert result.returncode == 2


def test_bad_subject_in_a_message_file_is_blocked(hook, feature_repo):
    (feature_repo / "message.txt").write_text("updated stuff\n")
    result = hook("commit_guard.py", "git commit -F message.txt", cwd=str(feature_repo))
    assert result.returncode == 2
    assert "Conventional Commit" in result.stderr


def test_human_co_author_in_a_heredoc_is_allowed(hook, feature_repo):
    command = "git commit -F - <<'EOF'\nfeat: x\n\nCo-Authored-By: Jane <jane@example.com>\nEOF"
    result = hook("commit_guard.py", command, cwd=str(feature_repo), env=AI_ENV)
    assert result.returncode == 0, result.stderr
