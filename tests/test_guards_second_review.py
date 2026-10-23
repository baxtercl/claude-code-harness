"""Gaps and false blocks found in the second review of the 0.2.0 guards."""

import subprocess

import pytest
from test_data_guard import bash as data_bash
from test_data_guard import decision, event_run

COMMIT = 'git commit -m "feat: x"'


def init_repo(path, branch):
    path.mkdir()

    def run(*args):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)

    run("init", "-q", "-b", branch)
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "T")
    run("commit", "-q", "--allow-empty", "-m", "chore: init")
    return path


@pytest.fixture
def repos(tmp_path):
    """A repository on main, and another one on a feature branch to run from."""
    main = init_repo(tmp_path / "main-repo", "main")
    feature = init_repo(tmp_path / "work", "feature/x")
    return main, feature


def commit_guard(hook, command, cwd, env=None):
    return hook("commit_guard.py", command, cwd=str(cwd), env=env)


def test_commit_in_another_repository_on_main_is_found(hook, repos):
    main, feature = repos
    commands = [
        f'cd "{main}" && {COMMIT}',
        f"echo hi; cd {main} && {COMMIT}",
        f"true && cd {main} && {COMMIT}",
        f"(cd {main} && {COMMIT})",
        f"{{ cd {main}; {COMMIT}; }}",
        f"cd -- {main} && {COMMIT}",
        f"pushd {main} && {COMMIT}",
        f"cd {main.parent} && cd main-repo && {COMMIT}",
        f"GIT_DIR={main}/.git {COMMIT}",
        f"git --git-dir={main}/.git commit -m 'feat: x'",
        f"git --git-dir {main}/.git commit -m 'feat: x'",
        f"git -C {main} commit -m 'feat: x'",
    ]
    for command in commands:
        result = commit_guard(hook, command, feature)
        assert result.returncode == 2, command
        assert "protected" in result.stderr, command


def test_commit_from_a_feature_branch_directory_is_allowed(hook, repos):
    main, feature = repos
    assert commit_guard(hook, f"cd {feature} && {COMMIT}", main).returncode == 0
    assert commit_guard(hook, COMMIT, feature).returncode == 0


def test_a_directory_that_does_not_exist_yet_falls_back_to_the_working_directory(hook, repos):
    main, feature = repos
    command = f"git clone x new && cd new && {COMMIT}"
    assert commit_guard(hook, command, main).returncode == 2
    assert commit_guard(hook, command, feature).returncode == 0


@pytest.mark.parametrize(
    "command",
    [
        'git com\\\nmit -m "feat: x"',
        'g\\\nit commit -m "feat: x"',
        "git $'commit' -m \"feat: x\"",
        "$'git' commit -m \"feat: x\"",
        f"cat <<EOF\n$({COMMIT})\nEOF",
        f"cat <<EOF\n`{COMMIT}`\nEOF",
        f"echo $(( $({COMMIT}) + 1 ))",
        f"bash -c -l '{COMMIT}'",
        f"bash -c -- '{COMMIT}'",
        f"fish -c '{COMMIT}'",
        f"su -c '{COMMIT}'",
        f"busybox sh -c '{COMMIT}'",
        f"cmd /c {COMMIT}",
        f'powershell -Command "{COMMIT}"',
        f"echo {COMMIT} | bash",
        f"flock /tmp/l {COMMIT}",
        f"arch -arm64 {COMMIT}",
    ],
)
def test_more_ways_to_run_a_commit_are_found(hook, git_repo, command):
    result = commit_guard(hook, command, git_repo)
    assert result.returncode == 2, command


@pytest.fixture
def feature_repo(tmp_path):
    return init_repo(tmp_path / "feature-repo", "feature/y")


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m \"$(cat <<'EOF'\nfeat: handle the (parser\nEOF\n)\"",
        "git commit -m \"$(cat <<'EOF'\nfeat: x\n\nbody with :( and ((\nEOF\n)\"",
        "cat <<\\EOF\nit's quoted\nEOF",
        "cat <<END-OF\nit's quoted\nEND-OF",
        "git commit -m 'feat: x' \\",
        "git commit -m $'feat: x'",
        'git commit -m "$MSG"',
        'git commit -m "$(echo feat: x)"',
        "git commit -m \"Merge branch 'x'\"",
        "git commit -m 'feat: x'  # a comment with 'quotes",
        "cat <<'EOF'\n$(git commit -m bad)\nEOF",
    ],
)
def test_legitimate_commands_are_not_blocked(hook, feature_repo, command):
    result = commit_guard(hook, command, feature_repo)
    assert result.returncode == 0, (command, result.stderr)


def test_long_option_abbreviations_are_still_checked(hook, feature_repo):
    for command in ['git commit --mess "bad"', 'git commit --mes="bad"']:
        assert commit_guard(hook, command, feature_repo).returncode == 2, command
    env = {"HARNESS_BLOCK_AI_TRAILERS": "1"}
    command = 'git commit -m "feat: x" --trai "Co-Authored-By: Claude <a@b>"'
    assert commit_guard(hook, command, feature_repo, env).returncode == 2


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ../..",
        "rm -rf ../../..",
        "rm -rf /Users/baxter/*",
        "rm -rf /home/bob/*",
        "rm -rf /[a-z]*",
        "rm -rf /?*",
        "rm -rf /u*",
        "rm -rf /Volumes",
        "rm -rf /mnt",
        "rm -rf /usr/local",
        "rm -rf /private/var/*",
        "rm -rf .git/*",
        "rm -rf .*",
        "rm -rf .[!.]*",
        "rm -rf {/,x}",
        "rm -rf /{a,b}",
        "cd / && rm -rf Users",
        "cd /usr && rm -rf local",
        "cd ~ && rm -rf Documents",
        "cd src && rm -rf .",
        "rm -rf /c/Users/bob",
        "rm -rf /mnt/c/Users/bob",
        "fish -c 'rm -rf /'",
        "su -c 'rm -rf /'",
        "cmd /c rm -rf /",
        "echo rm -rf / | bash",
        "rm \\\n-rf /",
        "rm -rf $'/'",
    ],
)
def test_rm_guard_second_review_targets(hook, command):
    result = hook("rm_guard.py", command)
    assert result.returncode == 2, command


@pytest.mark.parametrize(
    "command",
    ["rm -rf my\\ docs", "rm -rf docs\\ old", "cd build && rm -rf out", "rm -rf .git/index.lock"],
)
def test_rm_guard_second_review_allowed(hook, command):
    assert hook("rm_guard.py", command).returncode == 0, command


DATA_BLOCKED = [
    ">data/app.db",
    "cd data && > app.db",
    ": > data/uploads/logo.png",
    "rsync -a --delete /empty/ data/",
    "rm data/{app.db,x}",
    "rm data/app.{db,bak}",
    "find data -delete",
    "find data/uploads -type f -delete",
    "find data -name '*.db' -exec rm {} +",
    "pushd data && rm app.db",
]
DATA_ALLOWED = [
    "sqlite3 -readonly data/app.db \"select * from t where k='update'\"",
    "sqlite3 -readonly data/app.db \"select replace(name, 'a', 'b') from t\"",
    "echo alembic upgrade head",
    "find data -name '*.tmp'",
    "rsync -a /src/ data/other/",
]


@pytest.mark.parametrize("command", DATA_BLOCKED)
def test_data_guard_second_review_blocked(command, tmp_path):
    (tmp_path / "backups").mkdir()
    assert data_bash(command, tmp_path).returncode == 2, command


def test_absolute_cd_inside_the_project_is_followed(tmp_path):
    (tmp_path / "backups").mkdir()
    assert data_bash(f"cd {tmp_path}/data && rm app.db", tmp_path).returncode == 2
    assert data_bash("cd /tmp && rm app.db", tmp_path).returncode == 0


@pytest.mark.parametrize("command", DATA_ALLOWED)
def test_data_guard_second_review_allowed(command, tmp_path):
    (tmp_path / "backups").mkdir()
    result = data_bash(command, tmp_path)
    assert result.returncode == 0, (command, result.stderr)
    assert decision(result) is None


def test_data_guard_checks_the_path_key_of_other_file_tools(tmp_path):
    event = {"tool_name": "Write", "tool_input": {"path": str(tmp_path / "data" / "app.db")}}
    assert event_run(event, tmp_path).returncode == 2
