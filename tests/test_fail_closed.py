import subprocess
import sys

from conftest import HOOKS

GUARDS = ["rm_guard.py", "secret_file_guard.py", "commit_guard.py", "data_guard.py"]


def test_malformed_input_blocks_instead_of_allowing():
    for guard in GUARDS:
        result = subprocess.run(
            [sys.executable, str(HOOKS / guard)],
            input="{not json",
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2, guard
        assert "the guard itself failed" in result.stderr


def test_empty_input_allows():
    for guard in GUARDS:
        result = subprocess.run(
            [sys.executable, str(HOOKS / guard)],
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, guard
