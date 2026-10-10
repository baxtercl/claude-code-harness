import pytest

BLOCKED = [
    "cat .env",
    "cat backend/.env",
    "less .env.local",
    "cat .env.e2e-users.local",
    "head .env.production",
    "cp .env .env.bak-2026",
    "grep KEY ./config/.env",
    'cat "$HOME/.env"',
    "cat server.pem",
    "openssl rsa -in private.key",
    "cat service-account-prod.json",
    "cat gcp-credentials.json",
    "cat ~/.ssh/id_ed25519",
]

ALLOWED = [
    "cat .env.example",
    "cp .env.example .env.sample",
    "cat .env.template",
    "python3 tools/env_inspect.py .env",
    'echo "remember to fill the .env file"',
    "git commit -m 'docs: explain how to create the .env file'",
    "npm run build",
    "pytest tests/",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_secret_files(hook, command):
    result = hook("secret_file_guard.py", command)
    assert result.returncode == 2, result.stderr
    assert "secret-file-guard" in result.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_templates_prose_and_inspector(hook, command):
    result = hook("secret_file_guard.py", command)
    assert result.returncode == 0, result.stderr
