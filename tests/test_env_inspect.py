import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("env_inspect", ROOT / "tools" / "env_inspect.py")
env_inspect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env_inspect)

SAMPLE = """
# comment
DEBUG=true
WORKERS=4
DATABASE_URL=postgresql://app_user:s3cr3t@localhost:5432/app
OPENAI_API_KEY=sk-abcdef1234567890
export FEATURE_X=off
EMPTY=
"""


def test_keeps_safe_values_and_redacts_secrets():
    out = dict(line.split("=", 1) for line in env_inspect.inspect(SAMPLE))
    assert out["DEBUG"] == "true"
    assert out["WORKERS"] == "4"
    assert out["FEATURE_X"] == "off"
    assert out["DATABASE_URL"] == "postgresql://app_user:***@localhost:5432/app"
    assert out["OPENAI_API_KEY"] == "***REDACTED*** (19 chars)"
    assert out["EMPTY"] == ""


def test_never_prints_a_secret():
    text = "\n".join(env_inspect.inspect(SAMPLE))
    assert "s3cr3t" not in text
    assert "sk-abcdef" not in text
