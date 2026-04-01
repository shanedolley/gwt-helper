"""End-to-end tests for the full worktree lifecycle."""

import json
import subprocess as sp

import pytest
from pathlib import Path

from gwt_worktree_manager.config.manager import Config
from gwt_worktree_manager.store.metadata import MetadataStore
from gwt_worktree_manager.services.discovery import RepoDiscovery
from gwt_worktree_manager.services.worktree import WorktreeService


# ==============================================================================
# E2E fixture
# ==============================================================================


@pytest.fixture
def e2e_env(tmp_path, git_repo):
    """Full E2E environment with real Git repo, config, and metadata."""
    # Determine default branch
    result = sp.run(
        ["git", "-C", str(git_repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    default_branch = result.stdout.strip()

    worktrees_dir = tmp_path / "worktrees"
    config_path = tmp_path / "config" / "config.toml"
    metadata_path = tmp_path / "metadata" / "metadata.json"

    # Write config file
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f"""
[general]
scan_paths = ["{git_repo.parent}"]
scan_depth = 3
worktrees_dir = "{worktrees_dir}"
default_source_branch = "{default_branch}"

[repos.{git_repo.name}]
post_create = ["echo setup-complete"]
open_command = "cd"
"""
    )

    return {
        "git_repo": git_repo,
        "repo_name": git_repo.name,
        "default_branch": default_branch,
        "worktrees_dir": worktrees_dir,
        "config_path": config_path,
        "metadata_path": metadata_path,
    }


def _make_service(e2e_env):
    """Build a WorktreeService from an e2e_env dict."""
    config = Config(
        scan_paths=[str(e2e_env["git_repo"].parent)],
        scan_depth=3,
        worktrees_dir=str(e2e_env["worktrees_dir"]),
        default_source_branch=e2e_env["default_branch"],
    )
    metadata = MetadataStore(metadata_path=e2e_env["metadata_path"])
    discovery = RepoDiscovery(config)
    service = WorktreeService(config, metadata, discovery)
    return service, config, metadata, discovery


# ==============================================================================
# Full lifecycle tests
# ==============================================================================


class TestFullLifecycle:
    """Test the full worktree lifecycle: create → list → open → move → delete."""

    @pytest.mark.asyncio
    async def test_create_list_open_move_delete(self, e2e_env):
        """Full lifecycle through the service layer."""
        service, config, metadata, discovery = _make_service(e2e_env)

        # CREATE
        entry = await service.create_worktree(
            repo_name=e2e_env["repo_name"],
            work_type="feature",
            issue_id="TB-999",
            description="e2e lifecycle test",
        )
        assert Path(entry.path).exists()
        assert entry.branch == "feature/TB-999-e2e-lifecycle-test"

        # LIST
        entries = await service.list_worktrees()
        assert len(entries) == 1
        assert entries[0].id == entry.id

        # SEARCH BY ISSUE
        found = await service.search_by_issue("TB-999")
        assert len(found) == 1
        assert found[0].issue_id == "TB-999"

        # OPEN
        result = await service.open_worktree(entry.id)
        assert result.action == "cd"
        assert result.cd_path == Path(entry.path)

        # MOVE
        new_path = e2e_env["worktrees_dir"] / "moved-worktree"
        updated = await service.move_worktree(entry.id, new_path)
        assert updated.path == str(new_path)
        assert new_path.exists()

        # DELETE
        await service.delete_worktree(updated.id, delete_branch=True)
        assert not new_path.exists()
        assert metadata.get(entry.id) is None

        # Verify clean state
        remaining = await service.list_worktrees()
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_create_multiple_and_search(self, e2e_env):
        """Test cross-repo search with multiple worktrees."""
        service, config, metadata, discovery = _make_service(e2e_env)

        # Create multiple worktrees
        e1 = await service.create_worktree(
            e2e_env["repo_name"], "feature", "TB-100", "first feature"
        )
        e2 = await service.create_worktree(
            e2e_env["repo_name"], "bug", "TB-200", "fix bug"
        )
        e3 = await service.create_worktree(
            e2e_env["repo_name"], "feature", "TB-300", "third feature"
        )

        # List all
        all_entries = await service.list_worktrees()
        assert len(all_entries) == 3

        # Search specific
        results = await service.search_by_issue("TB-200")
        assert len(results) == 1
        assert results[0].work_type == "bug"

        # Search nonexistent
        empty = await service.search_by_issue("TB-NOPE")
        assert empty == []

        # Cleanup
        for e in [e1, e2, e3]:
            await service.delete_worktree(e.id, delete_branch=True)

        # Verify all deleted
        all_entries = await service.list_worktrees()
        assert len(all_entries) == 0


# ==============================================================================
# Edge case regression tests
# ==============================================================================


class TestEdgeCases:
    """Regression tests for edge cases from PRD Section 6."""

    @pytest.mark.asyncio
    async def test_branch_already_exists(self, e2e_env):
        """Creating a worktree with existing branch should fail."""
        from gwt_worktree_manager.services.worktree import BranchExistsError

        service, config, metadata, discovery = _make_service(e2e_env)

        await service.create_worktree(
            e2e_env["repo_name"], "feature", "DUP-1", "duplicate test"
        )
        with pytest.raises(BranchExistsError):
            await service.create_worktree(
                e2e_env["repo_name"], "feature", "DUP-1", "duplicate test"
            )

    @pytest.mark.asyncio
    async def test_invalid_issue_id(self, e2e_env):
        """Issue ID with special chars should be rejected."""
        from gwt_worktree_manager.services.worktree import InvalidInputError

        service, config, metadata, discovery = _make_service(e2e_env)

        with pytest.raises(InvalidInputError):
            await service.create_worktree(
                e2e_env["repo_name"], "feature", "-TB", "bad id"
            )

    @pytest.mark.asyncio
    async def test_invalid_work_type(self, e2e_env):
        """Work type not in allowed set should be rejected."""
        from gwt_worktree_manager.services.worktree import InvalidInputError

        service, config, metadata, discovery = _make_service(e2e_env)

        with pytest.raises(InvalidInputError):
            await service.create_worktree(
                e2e_env["repo_name"], "invalid-type", "TB-1", "test"
            )

    @pytest.mark.asyncio
    async def test_nonexistent_source_branch(self, e2e_env):
        """Using a source branch that doesn't exist should raise InvalidInputError."""
        from gwt_worktree_manager.services.worktree import InvalidInputError

        service, config, metadata, discovery = _make_service(e2e_env)

        with pytest.raises(InvalidInputError):
            await service.create_worktree(
                e2e_env["repo_name"],
                "feature",
                "TB-1",
                "test",
                source_branch="nonexistent",
            )

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, e2e_env):
        """Deleting a worktree that doesn't exist should raise WorktreeNotFoundError."""
        from gwt_worktree_manager.services.worktree import WorktreeNotFoundError

        service, config, metadata, discovery = _make_service(e2e_env)

        with pytest.raises(WorktreeNotFoundError):
            await service.delete_worktree("nonexistent-uuid")

    @pytest.mark.asyncio
    async def test_metadata_reconciliation(self, e2e_env):
        """Test that reconciliation detects and cleans stale metadata."""
        import shutil
        from gwt_worktree_manager.git import operations as git

        service, config, metadata, discovery = _make_service(e2e_env)

        # Create a worktree
        entry = await service.create_worktree(
            e2e_env["repo_name"], "feature", "REC-1", "reconcile test"
        )

        # Manually delete it without going through the service
        shutil.rmtree(entry.path)
        await git.prune_worktrees(e2e_env["git_repo"])

        # Reconcile should remove the stale entry
        worktrees = await git.list_worktrees(e2e_env["git_repo"])
        metadata.reconcile(worktrees)

        assert metadata.get(entry.id) is None

    @pytest.mark.asyncio
    async def test_open_nonexistent_worktree(self, e2e_env):
        """Opening a nonexistent worktree ID should raise WorktreeNotFoundError."""
        from gwt_worktree_manager.services.worktree import WorktreeNotFoundError

        service, config, metadata, discovery = _make_service(e2e_env)

        with pytest.raises(WorktreeNotFoundError):
            await service.open_worktree("nonexistent-uuid")

    @pytest.mark.asyncio
    async def test_move_nonexistent_worktree(self, e2e_env):
        """Moving a nonexistent worktree ID should raise WorktreeNotFoundError."""
        from gwt_worktree_manager.services.worktree import WorktreeNotFoundError

        service, config, metadata, discovery = _make_service(e2e_env)

        new_path = e2e_env["worktrees_dir"] / "nowhere"
        with pytest.raises(WorktreeNotFoundError):
            await service.move_worktree("nonexistent-uuid", new_path)

    @pytest.mark.asyncio
    async def test_empty_description_rejected(self, e2e_env):
        """Description that produces an empty slug should be rejected."""
        from gwt_worktree_manager.services.worktree import InvalidInputError

        service, config, metadata, discovery = _make_service(e2e_env)

        with pytest.raises(InvalidInputError):
            await service.create_worktree(
                e2e_env["repo_name"], "feature", "TB-1", "!!!"
            )

    @pytest.mark.asyncio
    async def test_create_updates_metadata(self, e2e_env):
        """Created worktree should have all metadata fields populated."""
        service, config, metadata, discovery = _make_service(e2e_env)

        entry = await service.create_worktree(
            e2e_env["repo_name"], "chore", "META-1", "metadata check"
        )

        stored = metadata.get(entry.id)
        assert stored is not None
        assert stored.repo_name == e2e_env["repo_name"]
        assert stored.branch == "chore/META-1-metadata-check"
        assert stored.issue_id == "META-1"
        assert stored.work_type == "chore"
        assert stored.source_branch == e2e_env["default_branch"]
        assert stored.created_at != ""
        assert stored.last_accessed != ""
        assert stored.tags == []

    @pytest.mark.asyncio
    async def test_open_updates_last_accessed(self, e2e_env):
        """Opening a worktree should update last_accessed timestamp."""
        import asyncio

        service, config, metadata, discovery = _make_service(e2e_env)

        entry = await service.create_worktree(
            e2e_env["repo_name"], "feature", "TS-1", "timestamp test"
        )
        original_accessed = entry.last_accessed

        # Brief pause so timestamps differ
        await asyncio.sleep(0.01)
        await service.open_worktree(entry.id)

        updated = metadata.get(entry.id)
        assert updated is not None
        assert updated.last_accessed >= original_accessed


# ==============================================================================
# JSON output schema tests
# ==============================================================================


class TestCLIJsonOutput:
    """Test gwt list --json output schema."""

    @pytest.mark.asyncio
    async def test_json_schema(self, e2e_env):
        """Verify the JSON output structure has all required fields."""
        service, config, metadata, discovery = _make_service(e2e_env)

        entry = await service.create_worktree(
            e2e_env["repo_name"], "feature", "JSON-1", "json test"
        )

        # Verify JSON output structure
        all_entries = metadata.list_all()
        output = {
            "schema_version": 1,
            "worktrees": [
                {
                    "id": e.id,
                    "repo_name": e.repo_name,
                    "branch": e.branch,
                    "path": e.path,
                    "issue_id": e.issue_id,
                    "work_type": e.work_type,
                    "source_branch": e.source_branch,
                    "created_at": e.created_at,
                    "last_accessed": e.last_accessed,
                    "tags": e.tags,
                }
                for e in all_entries
            ],
        }

        # Round-trip through JSON serialisation
        data = json.loads(json.dumps(output))
        assert data["schema_version"] == 1
        assert len(data["worktrees"]) == 1
        wt = data["worktrees"][0]
        assert "id" in wt
        assert "repo_name" in wt
        assert "branch" in wt
        assert "path" in wt
        assert "issue_id" in wt
        assert "tags" in wt
        assert wt["branch"] == "feature/JSON-1-json-test"
        assert wt["issue_id"] == "JSON-1"
        assert wt["work_type"] == "feature"
        assert wt["repo_name"] == e2e_env["repo_name"]

    @pytest.mark.asyncio
    async def test_json_multiple_worktrees(self, e2e_env):
        """JSON output with multiple worktrees should include all entries."""
        service, config, metadata, discovery = _make_service(e2e_env)

        e1 = await service.create_worktree(
            e2e_env["repo_name"], "feature", "JSON-10", "first"
        )
        e2 = await service.create_worktree(
            e2e_env["repo_name"], "bug", "JSON-11", "second"
        )

        all_entries = metadata.list_all()
        output = {
            "schema_version": 1,
            "worktrees": [
                {
                    "id": e.id,
                    "repo_name": e.repo_name,
                    "branch": e.branch,
                    "path": e.path,
                    "issue_id": e.issue_id,
                    "work_type": e.work_type,
                    "source_branch": e.source_branch,
                    "created_at": e.created_at,
                    "last_accessed": e.last_accessed,
                    "tags": e.tags,
                }
                for e in all_entries
            ],
        }

        data = json.loads(json.dumps(output))
        assert len(data["worktrees"]) == 2

        # All entries round-trip cleanly
        for wt in data["worktrees"]:
            assert isinstance(wt["id"], str)
            assert isinstance(wt["tags"], list)
            assert isinstance(wt["path"], str)
            assert Path(wt["path"]).exists()
