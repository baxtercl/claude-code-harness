"""rm on a catastrophic target must be found however the command line wraps it (review of 0.2.0)."""

import pytest

BLOCKED = [
    "rm -rf //",
    'rm -rf "sr"c',
    'rm -rf s"r"c',
    'rm -rf /"etc"',
    'rm -rf "/tm"p',
    "rm -rf /*",
    "rm -rf /tmp/*",
    "echo a & rm -rf /",
    "(rm -rf /)",
    "{ rm -rf /; }",
    'bash -c "rm -rf /"',
    "sh -c 'cd x && rm -rf /'",
    "echo `rm -rf /`",
    'echo "$(rm -rf /)"',
    "env -i rm -rf /",
    "sudo -u x rm -rf /",
    "time -p rm -rf /",
    "xargs rm -rf <<< /",
    "find . -exec rm -rf / \\;",
    "echo hi # don't\nrm -rf /",
    "rm -rf C:\\Windows",
    'rm -rf "C:\\Program Files"',
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_catastrophic_targets_however_they_are_wrapped(hook, command):
    result = hook("rm_guard.py", command)
    assert result.returncode == 2, command
    assert "rm-guard" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "echo 'rm -rf /' is dangerous",
        'echo "rm -rf /"',
        "rm -rf dist # rm -rf /",
        "rm -rf /tmp/mutation-copy-123/*",
        "sudo ls /",
    ],
)
def test_allows_text_and_disposable_targets(hook, command):
    result = hook("rm_guard.py", command)
    assert result.returncode == 0, result.stderr


def test_protected_names_on_windows_paths_ignore_case(hook):
    env = {"HARNESS_RM_PROTECTED": "Docs"}
    assert hook("rm_guard.py", "rm -rf C:\\p\\docs", env=env).returncode == 2
    assert hook("rm_guard.py", "rm -rf C:\\p\\DOCS", env=env).returncode == 2


def test_unreadable_command_fails_closed(hook):
    result = hook("rm_guard.py", 'rm -rf "oops')
    assert result.returncode == 2
    assert "the guard itself failed" in result.stderr
