"""Tests for WorktreeService — unit tests for helpers and integration tests."""

import subprocess
import pytest
from pathlib import Path

from gwt_worktree_manager.services.worktree import (
    WorktreeService,
    OpenResult,
    WorktreeNotFoundError,
    BranchExistsError,
    InvalidInputError,
    UncommittedChangesError,
    BranchCheckedOutError,
    to_kebab_case,
    generate_branch_name,
    validate_work_type,
    validate_issue_id,
)
from gwt_worktree_manager.config.manager import Config
from gwt_worktree_manager.store.metadata import MetadataStore
from gwt_worktree_manager.services.discovery import RepoDiscovery


# ==============================================================================
# Unit tests for helper functions
# ==============================================================================


class TestToKebabCase:
    def test_simple_text(self):
        assert to_kebab_case("add user profile") == "add-user-profile"

    def test_special_characters_removed(self):
        assert to_kebab_case("add user's profile!") == "add-users-profile"

    def test_uppercase_lowered(self):
        assert to_kebab_case("Add USER Profile") == "add-user-profile"

    def test_consecutive_hyphens_collapsed(self):
        assert to_kebab_case("add -- user") == "add-user"

    def test_leading_trailing_whitespace(self):
        assert to_kebab_case("  hello world  ") == "hello-world"

    def test_underscores_converted(self):
        assert to_kebab_case("add_user_profile") == "add-user-profile"

    def test_slashes_converted(self):
        assert to_kebab_case("add/user/profile") == "add-user-profile"


class TestGenerateBranchName:
    def test_standard_branch(self):
        result = generate_branch_name("feature", "TB-123", "add user profile")
        assert result == "feature/TB-123-add-user-profile"

    def test_empty_description_raises(self):
        with pytest.raises(InvalidInputError, match="empty branch slug"):
            generate_branch_name("bug", "TB-1", "!!!!")

    def test_too_long_raises(self):
        with pytest.raises(InvalidInputError, match="too long"):
            generate_branch_name("feature", "TB-123", "a" * 200)


class TestValidateWorkType:
    def test_valid_types(self):
        for wt in ["feature", "bug", "chore", "doc", "refactor", "hotfix"]:
            validate_work_type(wt)

    def test_invalid_type(self):
        with pytest.raises(InvalidInputError, match="Invalid work type"):
            validate_work_type("invalid")


class TestValidateIssueId:
    def test_valid_alphanumeric(self):
        validate_issue_id("TB123")

    def test_valid_with_hyphens(self):
        validate_issue_id("TB-123")

    def test_valid_numeric(self):
        validate_issue_id("12345")

    def test_empty_raises(self):
        with pytest.raises(InvalidInputError, match="cannot be empty"):
            validate_issue_id("")

    def test_leading_hyphen_raises(self):
        with pytest.raises(InvalidInputError, match="invalid"):
            validate_issue_id("-TB-123")

    def test_trailing_hyphen_raises(self):
        with pytest.raises(InvalidInputError, match="invalid"):
            validate_issue_id("TB-123-")

    def test_special_chars_raises(self):
        with pytest.raises(InvalidInputError):
            validate_issue_id("TB@123")


# ==============================================================================
# Integration test fixture
# ==============================================================================


@pytest.fixture
def worktree_env(tmp_path, git_repo):
    """Set up a complete worktree environment for testing."""
    result = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    default_branch = result.stdout.strip()

    worktrees_dir = tmp_path / "worktrees"
    metadata_path = tmp_path / "metadata" / "metadata.json"

    config = Config(
        scan_paths=[str(git_repo.parent)],
        scan_depth=3,
        worktrees_dir=str(worktrees_dir),
        default_source_branch=default_branch,
    )
    metadata = MetadataStore(metadata_path=metadata_path)
    discovery = RepoDiscovery(config)
    service = WorktreeService(config, metadata, discovery)

    return {
        "service": service,
        "config": config,
        "metadata": metadata,
        "repo_path": git_repo,
        "repo_name": git_repo.name,
        "default_branch": default_branch,
        "worktrees_dir": worktrees_dir,
    }


# ==============================================================================
# Integration tests
# ==============================================================================


class TestWorktreeServiceIntegration:
    @pytest.mark.asyncio
    async def test_create_worktree(self, worktree_env):
        svc = worktree_env["service"]
        entry = await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="feature",
            issue_id="TB-123",
            description="add user profile",
        )
        assert entry.branch == "feature/TB-123-add-user-profile"
        assert entry.issue_id == "TB-123"
        assert entry.work_type == "feature"
        assert Path(entry.path).exists()

    @pytest.mark.asyncio
    async def test_create_with_invalid_work_type(self, worktree_env):
        svc = worktree_env["service"]
        with pytest.raises(InvalidInputError, match="Invalid work type"):
            await svc.create_worktree(
                repo_name=worktree_env["repo_name"],
                work_type="invalid",
                issue_id="TB-1",
                description="test",
            )

    @pytest.mark.asyncio
    async def test_create_duplicate_branch_raises(self, worktree_env):
        svc = worktree_env["service"]
        await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="feature",
            issue_id="TB-1",
            description="first",
        )
        with pytest.raises(BranchExistsError):
            await svc.create_worktree(
                repo_name=worktree_env["repo_name"],
                work_type="feature",
                issue_id="TB-1",
                description="first",
            )

    @pytest.mark.asyncio
    async def test_delete_worktree(self, worktree_env):
        svc = worktree_env["service"]
        entry = await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="bug",
            issue_id="TB-456",
            description="fix login",
        )
        assert Path(entry.path).exists()
        await svc.delete_worktree(entry.id)
        assert not Path(entry.path).exists()
        assert worktree_env["metadata"].get(entry.id) is None

    @pytest.mark.asyncio
    async def test_delete_with_branch_cleanup(self, worktree_env):
        svc = worktree_env["service"]
        entry = await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="chore",
            issue_id="TB-789",
            description="cleanup",
        )
        await svc.delete_worktree(entry.id, delete_branch=True)
        from gwt_worktree_manager.git import operations as git_ops

        exists = await git_ops.branch_exists(
            worktree_env["repo_path"], entry.branch, check_remote=False
        )
        assert not exists

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises(self, worktree_env):
        with pytest.raises(WorktreeNotFoundError):
            await worktree_env["service"].delete_worktree("nonexistent-uuid")

    @pytest.mark.asyncio
    async def test_open_worktree_cd(self, worktree_env):
        svc = worktree_env["service"]
        entry = await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="feature",
            issue_id="TB-100",
            description="open test",
        )
        result = await svc.open_worktree(entry.id)
        assert result.action == "cd"
        assert result.cd_path == Path(entry.path)

    @pytest.mark.asyncio
    async def test_open_nonexistent_raises(self, worktree_env):
        with pytest.raises(WorktreeNotFoundError):
            await worktree_env["service"].open_worktree("bad-id")

    @pytest.mark.asyncio
    async def test_move_worktree(self, worktree_env):
        svc = worktree_env["service"]
        entry = await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="feature",
            issue_id="TB-200",
            description="move test",
        )
        old_path = Path(entry.path)
        new_path = worktree_env["worktrees_dir"] / "moved"
        updated = await svc.move_worktree(entry.id, new_path)
        assert updated.path == str(new_path)
        assert new_path.exists()
        assert not old_path.exists()

    @pytest.mark.asyncio
    async def test_list_worktrees(self, worktree_env):
        svc = worktree_env["service"]
        await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="feature",
            issue_id="TB-300",
            description="list test one",
        )
        await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="bug",
            issue_id="TB-301",
            description="list test two",
        )
        entries = await svc.list_worktrees()
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_list_worktrees_filtered(self, worktree_env):
        svc = worktree_env["service"]
        await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="feature",
            issue_id="TB-400",
            description="filter test",
        )
        entries = await svc.list_worktrees(repo_name="nonexistent")
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_search_by_issue(self, worktree_env):
        svc = worktree_env["service"]
        await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="feature",
            issue_id="TB-500",
            description="search test",
        )
        results = await svc.search_by_issue("TB-500")
        assert len(results) == 1
        assert results[0].issue_id == "TB-500"

    @pytest.mark.asyncio
    async def test_search_by_issue_no_results(self, worktree_env):
        results = await worktree_env["service"].search_by_issue("NONE-999")
        assert results == []

    @pytest.mark.asyncio
    async def test_switch_branch(self, worktree_env):
        svc = worktree_env["service"]
        subprocess.run(
            [
                "git",
                "-C",
                str(worktree_env["repo_path"]),
                "branch",
                "other-branch",
            ],
            check=True,
            capture_output=True,
        )
        entry = await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="feature",
            issue_id="TB-600",
            description="switch test",
        )
        updated = await svc.switch_branch(entry.id, "other-branch")
        assert updated.branch == "other-branch"

    @pytest.mark.asyncio
    async def test_switch_branch_not_found(self, worktree_env):
        svc = worktree_env["service"]
        entry = await svc.create_worktree(
            repo_name=worktree_env["repo_name"],
            work_type="feature",
            issue_id="TB-700",
            description="switch fail",
        )
        with pytest.raises(InvalidInputError, match="not found locally"):
            await svc.switch_branch(entry.id, "nonexistent-branch")

    @pytest.mark.asyncio
    async def test_create_with_invalid_source_branch(self, worktree_env):
        svc = worktree_env["service"]
        with pytest.raises(InvalidInputError, match="not found"):
            await svc.create_worktree(
                repo_name=worktree_env["repo_name"],
                work_type="feature",
                issue_id="TB-800",
                description="bad source",
                source_branch="nonexistent-source",
            )

    @pytest.mark.asyncio
    async def test_create_with_nonexistent_repo(self, worktree_env):
        svc = worktree_env["service"]
        with pytest.raises(WorktreeNotFoundError, match="not found"):
            await svc.create_worktree(
                repo_name="nonexistent-repo",
                work_type="feature",
                issue_id="TB-900",
                description="bad repo",
            )
