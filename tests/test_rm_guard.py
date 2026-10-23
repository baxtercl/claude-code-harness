import pytest

BLOCKED = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf ~/projects",
    "rm -rf $HOME",
    "rm -rf /Users/alice",
    "rm -rf /home/alice/",
    "rm -rf .",
    "rm -rf *",
    "rm -rf src",
    "rm -rf ./src/",
    "rm -r .git",
    "rm -rf .claude",
    "sudo rm -rf /etc",
    "npm run build && rm -rf docs",
    "FOO=1 rm -rf migrations",
    "rm -rf -- src",
]

ALLOWED = [
    "rm -rf dist",
    "rm -rf node_modules",
    "rm build/output.log",
    "rm -rf .pytest_cache coverage",
    "rm -rf /tmp/mutation-copy-123",
    "rm src/old_module.py",
    "echo 'rm -rf /' is dangerous",
    "git rm --cached file.txt",
    "ls -la",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_catastrophic_targets(hook, command):
    result = hook("rm_guard.py", command)
    assert result.returncode == 2, result.stderr
    assert "rm-guard" in result.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_disposable_targets(hook, command):
    result = hook("rm_guard.py", command)
    assert result.returncode == 0, result.stderr


def test_blocks_project_root(hook, tmp_path):
    result = hook("rm_guard.py", f"rm -rf {tmp_path}", env={"CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert result.returncode == 2


def test_protected_names_are_configurable(hook):
    env = {"HARNESS_RM_PROTECTED": "vendor"}
    assert hook("rm_guard.py", "rm -rf vendor", env=env).returncode == 2
    assert hook("rm_guard.py", "rm -rf src", env=env).returncode == 0


WINDOWS_PROJECT = r"C:\Users\alice\proj"


@pytest.mark.parametrize(
    "command",
    [
        rf"rm -rf {WINDOWS_PROJECT}",
        rf'rm -rf "{WINDOWS_PROJECT}"',
        rf"rm -rf {WINDOWS_PROJECT}\\",
        r"rm -rf c:/users/alice/proj",
        rf"rm -rf {WINDOWS_PROJECT}\src",
        r"rm -rf C:\Users\alice",
        r"rm -rf C:\\",
        r"rm -rf C:/",
    ],
)
def test_blocks_windows_paths(hook, command):
    result = hook("rm_guard.py", command, env={"CLAUDE_PROJECT_DIR": WINDOWS_PROJECT})
    assert result.returncode == 2, result.stderr


@pytest.mark.parametrize(
    "command",
    [
        rf"rm -rf {WINDOWS_PROJECT}\dist",
        rf'rm -rf "{WINDOWS_PROJECT}\build output"',
        r"rm -rf C:\Users\alice\other\cache",
    ],
)
def test_allows_disposable_windows_paths(hook, command):
    result = hook("rm_guard.py", command, env={"CLAUDE_PROJECT_DIR": WINDOWS_PROJECT})
    assert result.returncode == 0, result.stderr


def test_normalises_parent_references(hook):
    assert hook("rm_guard.py", "rm -rf foo/..").returncode == 2
    assert hook("rm_guard.py", "rm -rf src/../dist").returncode == 0
