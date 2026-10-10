import subprocess


def checkout(repo, branch):
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", branch], check=True)


def test_ignores_non_commit_commands(hook, git_repo):
    assert hook("commit_guard.py", "git status", cwd=str(git_repo)).returncode == 0


def test_blocks_commit_on_protected_branch(hook, git_repo):
    result = hook("commit_guard.py", "git commit -m 'feat: add search'", cwd=str(git_repo))
    assert result.returncode == 2
    assert "protected" in result.stderr


def test_allows_commit_on_feature_branch(hook, git_repo):
    checkout(git_repo, "feature/search")
    result = hook("commit_guard.py", "git commit -m 'feat(search): add filters'", cwd=str(git_repo))
    assert result.returncode == 0, result.stderr


def test_blocks_direct_commit_on_merge_only_branch(hook, git_repo):
    checkout(git_repo, "develop")
    result = hook("commit_guard.py", "git commit -m 'fix: typo'", cwd=str(git_repo))
    assert result.returncode == 2
    assert "only receives merges" in result.stderr


def test_allows_concluding_a_merge_on_merge_only_branch(hook, git_repo):
    checkout(git_repo, "develop")
    git_dir = git_repo / ".git"
    (git_dir / "MERGE_HEAD").write_text("0" * 40)
    result = hook("commit_guard.py", "git commit -m 'chore: merge feature/x'", cwd=str(git_repo))
    assert result.returncode == 0, result.stderr


def test_resolves_git_dash_c_directory(hook, git_repo, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    result = hook("commit_guard.py", f"git -C {git_repo} commit -m 'feat: x'", cwd=str(elsewhere))
    assert result.returncode == 2


def test_rejects_non_conventional_message(hook, git_repo):
    checkout(git_repo, "feature/x")
    result = hook("commit_guard.py", "git commit -m 'updated stuff'", cwd=str(git_repo))
    assert result.returncode == 2
    assert "Conventional Commit" in result.stderr


def test_conventional_check_can_be_disabled(hook, git_repo):
    checkout(git_repo, "feature/x")
    env = {"HARNESS_CONVENTIONAL_COMMITS": "0"}
    result = hook("commit_guard.py", "git commit -m 'updated stuff'", cwd=str(git_repo), env=env)
    assert result.returncode == 0


def test_ai_trailer_check_is_off_by_default(hook, git_repo):
    checkout(git_repo, "feature/x")
    cmd = "git commit -m 'feat: x' -m 'Co-Authored-By: Claude <noreply@anthropic.com>'"
    assert hook("commit_guard.py", cmd, cwd=str(git_repo)).returncode == 0


def test_ai_trailer_check_when_enabled(hook, git_repo):
    checkout(git_repo, "feature/x")
    env = {"HARNESS_BLOCK_AI_TRAILERS": "1"}
    cmd = "git commit -m 'feat: x' -m 'Co-Authored-By: Claude <noreply@anthropic.com>'"
    result = hook("commit_guard.py", cmd, cwd=str(git_repo), env=env)
    assert result.returncode == 2


def test_mentioning_claude_md_is_not_an_ai_trailer(hook, git_repo):
    checkout(git_repo, "feature/x")
    env = {"HARNESS_BLOCK_AI_TRAILERS": "1"}
    cmd = "git commit -m 'docs: update CLAUDE.md'"
    result = hook("commit_guard.py", cmd, cwd=str(git_repo), env=env)
    assert result.returncode == 0, result.stderr
