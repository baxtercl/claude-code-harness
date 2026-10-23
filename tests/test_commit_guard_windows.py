"""On Windows an unquoted path keeps its backslashes (`git -C C:\\repo`, `cd C:\\repo`)."""

import sys

from conftest import HOOKS

sys.path.insert(0, str(HOOKS))
from commit_guard import commits_in  # noqa: E402

COMMAND = r"cd C:\Users\x\repo && git -C C:\Users\x\other commit -m 'feat: x'"


def test_windows_paths_survive_when_the_platform_is_windows():
    (commit,) = commits_in(COMMAND, windows=True)
    assert commit.dirs == [r"C:\Users\x\repo", r"C:\Users\x\other"]


def test_posix_tokenizing_treats_backslashes_as_escapes():
    (commit,) = commits_in(COMMAND, windows=False)
    assert commit.dirs == ["C:Usersxrepo", "C:Usersxother"]
