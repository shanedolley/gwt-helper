"""Tests for the Git subprocess abstraction layer."""

import subprocess
import pytest
from unittest.mock import patch
from pathlib import Path

from gwt_worktree_manager.git.operations import (
    run_git_command,
    GitError,
    GitNotFoundError,
    GitVersionError,
    parse_worktree_list,
    validate_branch_name,
    get_git_version,
    check_git_version,
    create_worktree,
    list_worktrees,
    remove_worktree,
    move_worktree,
    prune_worktrees,
    list_branches,
    branch_exists,
    delete_branch,
    checkout_branch,
    get_current_branch,
    get_worktree_status,
)


class TestRunGitCommand:
    @pytest.mark.asyncio
    async def test_returns_stdout_stderr_returncode(self):
        stdout, stderr, code = await run_git_command(["--version"])
        assert code == 0
        assert "git version" in stdout
        assert isinstance(stderr, str)

    @pytest.mark.asyncio
    async def test_raises_git_not_found_error(self):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            with pytest.raises(GitNotFoundError):
                await run_git_command(["--version"])

    @pytest.mark.asyncio
    async def test_returns_nonzero_on_failure(self):
        stdout, stderr, code = await run_git_command(
            ["rev-parse", "--verify", "refs/heads/nonexistent-branch-that-cannot-exist"]
        )
        assert code != 0

    @pytest.mark.asyncio
    async def test_passes_cwd_to_subprocess(self, tmp_path):
        stdout, stderr, code = await run_git_command(["rev-parse", "--show-toplevel"], cwd=tmp_path)
        # Will fail because tmp_path is not a git repo, but cwd was passed
        assert isinstance(code, int)


class TestParseWorktreeList:
    def test_parses_single_worktree(self):
        output = "worktree /repo\nHEAD abc123\nbranch refs/heads/main\n\n"
        result = parse_worktree_list(output)
        assert len(result) == 1
        assert result[0].path == "/repo"
        assert result[0].branch == "main"
        assert result[0].head == "abc123"

    def test_parses_multiple_worktrees(self):
        output = (
            "worktree /repo\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /wt1\nHEAD def\nbranch refs/heads/feature/x\n\n"
        )
        result = parse_worktree_list(output)
        assert len(result) == 2
        assert result[1].branch == "feature/x"

    def test_parses_detached_head(self):
        output = "worktree /repo\nHEAD abc123\ndetached\n\n"
        result = parse_worktree_list(output)
        assert result[0].branch is None

    def test_parses_bare_repo(self):
        output = "worktree /repo\nHEAD abc123\nbare\n\n"
        result = parse_worktree_list(output)
        assert result[0].is_bare is True

    def test_parses_locked_worktree(self):
        output = "worktree /repo\nHEAD abc\nbranch refs/heads/main\nlocked\n\n"
        result = parse_worktree_list(output)
        assert result[0].is_locked is True

    def test_parses_prunable_worktree(self):
        output = "worktree /repo\nHEAD abc\nbranch refs/heads/main\nprunable\n\n"
        result = parse_worktree_list(output)
        assert result[0].is_prunable is True

    def test_empty_output_returns_empty_list(self):
        assert parse_worktree_list("") == []

    def test_handles_no_trailing_newline(self):
        output = "worktree /repo\nHEAD abc\nbranch refs/heads/main"
        result = parse_worktree_list(output)
        assert len(result) == 1

    def test_non_refs_heads_branch_preserved(self):
        output = "worktree /repo\nHEAD abc\nbranch refs/remotes/origin/main\n\n"
        result = parse_worktree_list(output)
        assert result[0].branch == "refs/remotes/origin/main"

    def test_parses_locked_with_reason(self):
        output = "worktree /repo\nHEAD abc\nbranch refs/heads/main\nlocked reason goes here\n\n"
        result = parse_worktree_list(output)
        assert result[0].is_locked is True

    def test_parses_prunable_with_reason(self):
        output = "worktree /repo\nHEAD abc\nbranch refs/heads/main\nprunable gitdir file points to non-existent location\n\n"
        result = parse_worktree_list(output)
        assert result[0].is_prunable is True


class TestValidateBranchName:
    def test_valid_simple_branch(self):
        validate_branch_name("main")  # Should not raise

    def test_valid_branch_with_slash(self):
        validate_branch_name("feature/TB-123-add-profile")

    def test_valid_branch_with_dots(self):
        validate_branch_name("release/1.2.3")

    def test_valid_branch_with_underscore_like_char(self):
        validate_branch_name("feature/my-branch-123")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_branch_name("")

    def test_rejects_shell_metacharacters(self):
        for bad in ["feat;rm -rf", "feat$(cmd)", "feat`cmd`", "feat|pipe", "feat&bg"]:
            with pytest.raises(ValueError, match="invalid characters"):
                validate_branch_name(bad)

    def test_rejects_leading_dash(self):
        with pytest.raises(ValueError, match="cannot start with a dash"):
            validate_branch_name("-branch")

    def test_rejects_space(self):
        with pytest.raises(ValueError, match="invalid characters"):
            validate_branch_name("feature branch")

    def test_rejects_at_sign(self):
        with pytest.raises(ValueError, match="invalid characters"):
            validate_branch_name("feature@branch")


class TestGitVersion:
    @pytest.mark.asyncio
    async def test_parses_standard_version(self):
        with patch("gwt_worktree_manager.git.operations.run_git_command") as mock:
            mock.return_value = ("git version 2.39.0\n", "", 0)
            version = await get_git_version()
            assert version == "2.39.0"

    @pytest.mark.asyncio
    async def test_parses_apple_git_version(self):
        with patch("gwt_worktree_manager.git.operations.run_git_command") as mock:
            mock.return_value = ("git version 2.39.0 (Apple Git-143)\n", "", 0)
            version = await get_git_version()
            assert version == "2.39.0"

    @pytest.mark.asyncio
    async def test_check_version_passes_for_new_git(self):
        with patch("gwt_worktree_manager.git.operations.get_git_version") as mock:
            mock.return_value = "2.39.0"
            v = await check_git_version("2.20.0")
            assert v == "2.39.0"

    @pytest.mark.asyncio
    async def test_check_version_fails_for_old_git(self):
        with patch("gwt_worktree_manager.git.operations.get_git_version") as mock:
            mock.return_value = "2.17.0"
            with pytest.raises(GitVersionError, match="too old"):
                await check_git_version("2.20.0")

    @pytest.mark.asyncio
    async def test_get_version_raises_on_command_failure(self):
        with patch("gwt_worktree_manager.git.operations.run_git_command") as mock:
            mock.return_value = ("", "error", 1)
            with pytest.raises(GitError):
                await get_git_version()

    @pytest.mark.asyncio
    async def test_get_version_raises_on_unparseable_output(self):
        with patch("gwt_worktree_manager.git.operations.run_git_command") as mock:
            mock.return_value = ("not a version string at all\n", "", 0)
            with pytest.raises(GitError):
                await get_git_version()

    @pytest.mark.asyncio
    async def test_check_version_equal_to_minimum_passes(self):
        with patch("gwt_worktree_manager.git.operations.get_git_version") as mock:
            mock.return_value = "2.20.0"
            v = await check_git_version("2.20.0")
            assert v == "2.20.0"


class TestGitErrorExceptions:
    def test_git_error_message_includes_returncode(self):
        err = GitError(["git", "status"], "something went wrong", 128)
        assert "128" in str(err)
        assert "something went wrong" in str(err)

    def test_git_not_found_error_is_git_error(self):
        err = GitNotFoundError()
        assert isinstance(err, GitError)
        assert err.returncode == 127

    def test_git_version_error_message(self):
        err = GitVersionError("2.17.0", "2.20.0")
        assert "2.17.0" in str(err)
        assert "too old" in str(err)
        assert err.version == "2.17.0"
        assert err.minimum == "2.20.0"


class TestGitIntegration:
    """Integration tests using real temporary Git repos."""

    @pytest.mark.asyncio
    async def test_create_and_list_worktree(self, git_repo, tmp_path):
        wt_path = tmp_path / "worktrees" / "feature-test"
        default_branch = _get_default_branch(git_repo)
        await create_worktree(git_repo, "feature/test", wt_path, default_branch)
        assert wt_path.exists()
        worktrees = await list_worktrees(git_repo)
        branches = [w.branch for w in worktrees]
        assert "feature/test" in branches

    @pytest.mark.asyncio
    async def test_remove_worktree(self, git_repo, tmp_path):
        wt_path = tmp_path / "worktrees" / "to-remove"
        default_branch = _get_default_branch(git_repo)
        await create_worktree(git_repo, "feature/remove", wt_path, default_branch)
        assert wt_path.exists()
        await remove_worktree(git_repo, wt_path)
        assert not wt_path.exists()

    @pytest.mark.asyncio
    async def test_move_worktree(self, git_repo, tmp_path):
        old_path = tmp_path / "worktrees" / "old"
        new_path = tmp_path / "worktrees" / "new"
        default_branch = _get_default_branch(git_repo)
        await create_worktree(git_repo, "feature/moveme", old_path, default_branch)
        await move_worktree(git_repo, old_path, new_path)
        assert not old_path.exists()
        assert new_path.exists()

    @pytest.mark.asyncio
    async def test_prune_after_manual_delete(self, git_repo, tmp_path):
        import shutil

        wt_path = tmp_path / "worktrees" / "to-prune"
        default_branch = _get_default_branch(git_repo)
        await create_worktree(git_repo, "feature/prune", wt_path, default_branch)
        shutil.rmtree(wt_path)  # Manual delete without git
        await prune_worktrees(git_repo)
        worktrees = await list_worktrees(git_repo)
        branches = [w.branch for w in worktrees if w.branch]
        assert "feature/prune" not in branches

    @pytest.mark.asyncio
    async def test_branch_operations(self, git_repo):
        branches = await list_branches(git_repo)
        assert "main" in branches or "master" in branches

    @pytest.mark.asyncio
    async def test_branch_exists(self, git_repo):
        result = await branch_exists(git_repo, "main", check_remote=False)
        if not result:
            result = await branch_exists(git_repo, "master", check_remote=False)
        assert result

    @pytest.mark.asyncio
    async def test_branch_not_exists(self, git_repo):
        result = await branch_exists(git_repo, "nonexistent-branch-xyz", check_remote=False)
        assert not result

    @pytest.mark.asyncio
    async def test_get_current_branch(self, git_repo, tmp_path):
        wt_path = tmp_path / "worktrees" / "branch-test"
        default_branch = _get_default_branch(git_repo)
        await create_worktree(git_repo, "feature/check-branch", wt_path, default_branch)
        branch = await get_current_branch(wt_path)
        assert branch == "feature/check-branch"

    @pytest.mark.asyncio
    async def test_get_worktree_status(self, git_repo, tmp_path):
        wt_path = tmp_path / "worktrees" / "status-test"
        default_branch = _get_default_branch(git_repo)
        await create_worktree(git_repo, "feature/status", wt_path, default_branch)
        status = await get_worktree_status(wt_path)
        assert isinstance(status, str)  # Clean worktree = empty string

    @pytest.mark.asyncio
    async def test_checkout_branch(self, git_repo, tmp_path):
        default_branch = _get_default_branch(git_repo)
        subprocess.run(
            ["git", "-C", str(git_repo), "branch", "other-branch"],
            check=True,
            capture_output=True,
        )
        wt_path = tmp_path / "worktrees" / "checkout-test"
        await create_worktree(git_repo, "feature/co-test", wt_path, default_branch)
        await checkout_branch(wt_path, "other-branch")
        current = await get_current_branch(wt_path)
        assert current == "other-branch"

    @pytest.mark.asyncio
    async def test_delete_branch(self, git_repo, tmp_path):
        default_branch = _get_default_branch(git_repo)
        wt_path = tmp_path / "worktrees" / "del-branch"
        await create_worktree(git_repo, "feature/to-delete", wt_path, default_branch)
        await remove_worktree(git_repo, wt_path)
        await delete_branch(git_repo, "feature/to-delete")
        exists = await branch_exists(git_repo, "feature/to-delete", check_remote=False)
        assert not exists

    @pytest.mark.asyncio
    async def test_create_worktree_fails_duplicate_branch(self, git_repo, tmp_path):
        default_branch = _get_default_branch(git_repo)
        wt1 = tmp_path / "worktrees" / "dup1"
        wt2 = tmp_path / "worktrees" / "dup2"
        await create_worktree(git_repo, "feature/dup", wt1, default_branch)
        with pytest.raises(GitError):
            await create_worktree(git_repo, "feature/dup", wt2, default_branch)

    @pytest.mark.asyncio
    async def test_git_version_real(self):
        version = await get_git_version()
        parts = version.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    @pytest.mark.asyncio
    async def test_list_worktrees_includes_main_repo(self, git_repo):
        worktrees = await list_worktrees(git_repo)
        assert len(worktrees) >= 1
        paths = [w.path for w in worktrees]
        assert str(git_repo) in paths

    @pytest.mark.asyncio
    async def test_remove_worktree_force(self, git_repo, tmp_path):
        wt_path = tmp_path / "worktrees" / "force-remove"
        default_branch = _get_default_branch(git_repo)
        await create_worktree(git_repo, "feature/force-rm", wt_path, default_branch)
        # Add an untracked file to make the worktree "dirty" so normal remove might fail
        (wt_path / "untracked.txt").write_text("untracked")
        await remove_worktree(git_repo, wt_path, force=True)
        assert not wt_path.exists()


def _get_default_branch(repo_path: Path) -> str:
    """Detect the default branch name for a freshly-initialised repo."""
    result = subprocess.run(
        ["git", "-C", str(repo_path), "branch", "--list"],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        name = line.strip().lstrip("* ")
        if name in ("main", "master"):
            return name
    # Fall back to HEAD symbolic ref
    ref_result = subprocess.run(
        ["git", "-C", str(repo_path), "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    if ref_result.returncode == 0:
        return ref_result.stdout.strip()
    return "main"
