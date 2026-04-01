"""Tests for the CLI subcommands."""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from typer.testing import CliRunner

from gwt_worktree_manager.cli import app
from gwt_worktree_manager.store.metadata import MetadataStore, WorktreeEntry
from gwt_worktree_manager.services.worktree import (
    WorktreeNotFoundError,
    BranchExistsError,
    InvalidInputError,
    UncommittedChangesError,
    BranchCheckedOutError,
    OpenResult,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(**kwargs) -> WorktreeEntry:
    defaults = {
        "id": str(uuid.uuid4()),
        "repo_name": "my-repo",
        "branch": "feature/TB-1-test",
        "path": "/tmp/my-repo/feature/TB-1-test",
        "issue_id": "TB-1",
        "work_type": "feature",
        "source_branch": "main",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_accessed": "2026-01-01T00:00:00+00:00",
        "tags": [],
    }
    defaults.update(kwargs)
    return WorktreeEntry(**defaults)


# ---------------------------------------------------------------------------
# Version & help
# ---------------------------------------------------------------------------


class TestVersion:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "1.0.0" in result.stdout

    def test_version_short_flag(self):
        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert "1.0.0" in result.stdout

    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "create" in result.stdout
        assert "open" in result.stdout
        assert "delete" in result.stdout
        assert "list" in result.stdout

    def test_no_subcommand_launches_tui(self):
        with patch("gwt_worktree_manager.app.run_tui", return_value=None) as mock_tui:
            result = runner.invoke(app, [])
            assert result.exit_code == 0
            mock_tui.assert_called_once()

    def test_no_subcommand_cd_result_is_echoed(self):
        with patch("gwt_worktree_manager.app.run_tui", return_value="__GWT_CD__:/tmp/myrepo"):
            result = runner.invoke(app, [])
            assert result.exit_code == 0
            assert "__GWT_CD__:/tmp/myrepo" in result.stdout


# ---------------------------------------------------------------------------
# shell-init
# ---------------------------------------------------------------------------


class TestShellInit:
    def test_zsh_wrapper(self):
        result = runner.invoke(app, ["shell-init", "zsh"])
        assert result.exit_code == 0
        assert "GWT_SHELL_WRAPPER" in result.stdout
        assert "command gwt" in result.stdout
        assert "${match[1]}" in result.stdout

    def test_zsh_wrapper_default(self):
        # Default argument is zsh
        result = runner.invoke(app, ["shell-init"])
        assert result.exit_code == 0
        assert "GWT_SHELL_WRAPPER" in result.stdout
        assert "${match[1]}" in result.stdout

    def test_bash_wrapper(self):
        result = runner.invoke(app, ["shell-init", "bash"])
        assert result.exit_code == 0
        assert "BASH_REMATCH" in result.stdout
        assert "GWT_SHELL_WRAPPER" in result.stdout
        assert "command gwt" in result.stdout

    def test_unsupported_shell(self):
        result = runner.invoke(app, ["shell-init", "fish"])
        assert result.exit_code == 1

    def test_unsupported_shell_error_message(self):
        result = runner.invoke(app, ["shell-init", "fish"])
        assert "Unsupported shell" in result.output


# ---------------------------------------------------------------------------
# create command
# ---------------------------------------------------------------------------


class TestCreateCommand:
    def test_create_requires_all_options(self):
        result = runner.invoke(app, ["create"])
        assert result.exit_code != 0

    def test_create_missing_repo(self):
        result = runner.invoke(app, ["create", "--type", "feature", "--id", "TB-1", "--desc", "test"])
        assert result.exit_code != 0

    def test_create_missing_type(self):
        result = runner.invoke(app, ["create", "--repo", "test", "--id", "TB-1", "--desc", "test"])
        assert result.exit_code != 0

    def test_create_missing_id(self):
        result = runner.invoke(app, ["create", "--repo", "test", "--type", "feature", "--desc", "test"])
        assert result.exit_code != 0

    def test_create_missing_desc(self):
        result = runner.invoke(app, ["create", "--repo", "test", "--type", "feature", "--id", "TB-1"])
        assert result.exit_code != 0

    def test_create_with_invalid_work_type(self):
        result = runner.invoke(app, [
            "create", "--repo", "test", "--type", "invalid",
            "--id", "TB-1", "--desc", "test"
        ])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_create_success(self):
        entry = _make_entry()
        mock_svc = MagicMock()
        mock_svc.create_worktree = AsyncMock(return_value=entry)

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, [
                "create", "--repo", "my-repo", "--type", "feature",
                "--id", "TB-1", "--desc", "test feature"
            ])

        assert result.exit_code == 0
        assert "Created worktree:" in result.stdout
        assert entry.branch in result.stdout
        assert "Path:" in result.stdout

    def test_create_branch_exists_error(self):
        mock_svc = MagicMock()
        mock_svc.create_worktree = AsyncMock(side_effect=BranchExistsError("branch exists"))

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, [
                "create", "--repo", "my-repo", "--type", "feature",
                "--id", "TB-1", "--desc", "test"
            ])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_create_invalid_input_error(self):
        mock_svc = MagicMock()
        mock_svc.create_worktree = AsyncMock(side_effect=InvalidInputError("invalid input"))

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, [
                "create", "--repo", "my-repo", "--type", "feature",
                "--id", "TB-1", "--desc", "test"
            ])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_create_repo_not_found_error(self):
        mock_svc = MagicMock()
        mock_svc.create_worktree = AsyncMock(
            side_effect=WorktreeNotFoundError("repo not found")
        )

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, [
                "create", "--repo", "nonexistent", "--type", "feature",
                "--id", "TB-1", "--desc", "test"
            ])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_create_with_source_option(self):
        entry = _make_entry(source_branch="develop")
        mock_svc = MagicMock()
        mock_svc.create_worktree = AsyncMock(return_value=entry)

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, [
                "create", "--repo", "my-repo", "--type", "feature",
                "--id", "TB-1", "--desc", "test", "--source", "develop"
            ])

        assert result.exit_code == 0
        mock_svc.create_worktree.assert_called_once_with(
            "my-repo", "feature", "TB-1", "test", "develop"
        )


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------


class TestListCommand:
    def test_list_empty(self):
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    def test_list_empty_message(self):
        mock_svc = MagicMock()
        mock_svc._discovery.discover_repos = AsyncMock(return_value=[])
        mock_svc.list_worktrees = AsyncMock(return_value=[])

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "No worktrees found." in result.stdout

    def test_list_json_empty(self):
        result = runner.invoke(app, ["list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "schema_version" in data
        assert data["schema_version"] == 1
        assert "worktrees" in data

    def test_list_json_empty_worktrees(self):
        mock_svc = MagicMock()
        mock_svc._discovery.discover_repos = AsyncMock(return_value=[])
        mock_svc.list_worktrees = AsyncMock(return_value=[])

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["worktrees"] == []

    def test_list_json_with_entries(self):
        entry = _make_entry()
        mock_svc = MagicMock()
        mock_svc._discovery.discover_repos = AsyncMock(return_value=[])
        mock_svc.list_worktrees = AsyncMock(return_value=[entry])

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data["worktrees"]) == 1
        wt = data["worktrees"][0]
        assert wt["id"] == entry.id
        assert wt["repo_name"] == entry.repo_name
        assert wt["branch"] == entry.branch
        assert wt["path"] == entry.path
        assert wt["issue_id"] == entry.issue_id
        assert wt["work_type"] == entry.work_type
        assert wt["source_branch"] == entry.source_branch
        assert wt["created_at"] == entry.created_at
        assert wt["last_accessed"] == entry.last_accessed
        assert wt["tags"] == entry.tags

    def test_list_text_with_entries(self):
        entry = _make_entry()
        mock_svc = MagicMock()
        mock_svc._discovery.discover_repos = AsyncMock(return_value=[])
        mock_svc.list_worktrees = AsyncMock(return_value=[entry])

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert entry.repo_name in result.stdout
        assert entry.branch in result.stdout

    def test_list_text_shows_issue_id(self):
        entry = _make_entry(issue_id="TB-42")
        mock_svc = MagicMock()
        mock_svc._discovery.discover_repos = AsyncMock(return_value=[])
        mock_svc.list_worktrees = AsyncMock(return_value=[entry])

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "TB-42" in result.stdout

    def test_list_filter_by_repo(self):
        entry = _make_entry(repo_name="specific-repo")
        mock_svc = MagicMock()
        mock_svc.list_worktrees = AsyncMock(return_value=[entry])

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["list", "--repo", "specific-repo"])

        assert result.exit_code == 0
        mock_svc.list_worktrees.assert_called_once_with(repo_name="specific-repo")

    def test_list_json_short_flag(self):
        mock_svc = MagicMock()
        mock_svc._discovery.discover_repos = AsyncMock(return_value=[])
        mock_svc.list_worktrees = AsyncMock(return_value=[])

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["list", "-j"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "schema_version" in data


# ---------------------------------------------------------------------------
# open command
# ---------------------------------------------------------------------------


class TestOpenCommand:
    def test_open_not_found(self):
        mock_svc = MagicMock()
        mock_svc.search_by_issue = AsyncMock(return_value=[])

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["open", "TB-999"])

        assert result.exit_code == 1
        assert "No worktree found" in result.output

    def test_open_cd_without_wrapper(self):
        entry = _make_entry()
        open_result = OpenResult(
            worktree=entry, action="cd", cd_path=Path(entry.path)
        )
        mock_svc = MagicMock()
        mock_svc.search_by_issue = AsyncMock(return_value=[entry])
        mock_svc.open_worktree = AsyncMock(return_value=open_result)

        # Ensure GWT_SHELL_WRAPPER is not set
        env = {k: v for k, v in __import__("os").environ.items() if k != "GWT_SHELL_WRAPPER"}
        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            with patch.dict("os.environ", env, clear=True):
                result = runner.invoke(app, ["open", "TB-1"])

        assert result.exit_code == 1
        assert "Shell wrapper not detected" in result.output

    def test_open_cd_with_wrapper(self):
        entry = _make_entry()
        open_result = OpenResult(
            worktree=entry, action="cd", cd_path=Path(entry.path)
        )
        mock_svc = MagicMock()
        mock_svc.search_by_issue = AsyncMock(return_value=[entry])
        mock_svc.open_worktree = AsyncMock(return_value=open_result)

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            with patch.dict("os.environ", {"GWT_SHELL_WRAPPER": "1"}):
                result = runner.invoke(app, ["open", "TB-1"])

        assert result.exit_code == 0
        assert f"__GWT_CD__:{entry.path}" in result.stdout

    def test_open_command_action(self):
        entry = _make_entry()
        open_result = OpenResult(
            worktree=entry, action="command", command_executed="code ."
        )
        mock_svc = MagicMock()
        mock_svc.search_by_issue = AsyncMock(return_value=[entry])
        mock_svc.open_worktree = AsyncMock(return_value=open_result)

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            with patch("gwt_worktree_manager.cli.subprocess.run") as mock_run:
                result = runner.invoke(app, ["open", "TB-1"])

        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            "code .",
            shell=True,
            cwd=entry.path,
        )

    def test_open_multiple_results_selects_one(self):
        entry1 = _make_entry(id="id-1", repo_name="repo-a", branch="feature/TB-1-a")
        entry2 = _make_entry(id="id-2", repo_name="repo-b", branch="feature/TB-1-b")
        open_result = OpenResult(
            worktree=entry1, action="cd", cd_path=Path(entry1.path)
        )
        mock_svc = MagicMock()
        mock_svc.search_by_issue = AsyncMock(return_value=[entry1, entry2])
        mock_svc.open_worktree = AsyncMock(return_value=open_result)

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            with patch.dict("os.environ", {"GWT_SHELL_WRAPPER": "1"}):
                result = runner.invoke(app, ["open", "TB-1"], input="1\n")

        assert result.exit_code == 0
        assert "Multiple worktrees match" in result.output
        mock_svc.open_worktree.assert_called_once_with("id-1")

    def test_open_multiple_results_invalid_selection(self):
        entry1 = _make_entry(id="id-1")
        entry2 = _make_entry(id="id-2")
        mock_svc = MagicMock()
        mock_svc.search_by_issue = AsyncMock(return_value=[entry1, entry2])

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["open", "TB-1"], input="99\n")

        assert result.exit_code == 1

    def test_open_worktree_not_found_error(self):
        entry = _make_entry()
        mock_svc = MagicMock()
        mock_svc.search_by_issue = AsyncMock(return_value=[entry])
        mock_svc.open_worktree = AsyncMock(
            side_effect=WorktreeNotFoundError("not found")
        )

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["open", "TB-1"])

        assert result.exit_code == 1
        assert "Error" in result.output


# ---------------------------------------------------------------------------
# delete command
# ---------------------------------------------------------------------------


class TestDeleteCommand:
    def test_delete_not_found(self):
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = []
        mock_metadata.find_by_branch.return_value = None
        mock_metadata.find_by_path.return_value = None

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["delete", "nonexistent"])

        assert result.exit_code == 1
        assert "No worktree found" in result.output

    def test_delete_aborted(self):
        entry = _make_entry()
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            # Input "n" to abort the confirmation
            result = runner.invoke(app, ["delete", "TB-1"], input="n\n")

        assert result.exit_code != 0

    def test_delete_confirmed(self):
        entry = _make_entry()
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.delete_worktree = AsyncMock(return_value=None)

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["delete", "TB-1"], input="y\n")

        assert result.exit_code == 0
        assert "Deleted worktree:" in result.stdout
        mock_svc.delete_worktree.assert_called_once_with(entry.id, delete_branch=False)

    def test_delete_with_branch_flag(self):
        entry = _make_entry()
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.delete_worktree = AsyncMock(return_value=None)

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["delete", "--branch", "TB-1"], input="y\n")

        assert result.exit_code == 0
        assert "Deleted branch:" in result.stdout
        mock_svc.delete_worktree.assert_called_once_with(entry.id, delete_branch=True)

    def test_delete_uncommitted_changes_error(self):
        entry = _make_entry()
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.delete_worktree = AsyncMock(
            side_effect=UncommittedChangesError("uncommitted changes")
        )

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["delete", "TB-1"], input="y\n")

        assert result.exit_code == 1
        assert "Error" in result.output


# ---------------------------------------------------------------------------
# move command
# ---------------------------------------------------------------------------


class TestMoveCommand:
    def test_move_not_found(self):
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = []
        mock_metadata.find_by_branch.return_value = None
        mock_metadata.find_by_path.return_value = None

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["move", "nonexistent", "/new/path"])

        assert result.exit_code == 1
        assert "No worktree found" in result.output

    def test_move_success(self):
        entry = _make_entry()
        updated = _make_entry(path="/new/path")
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.move_worktree = AsyncMock(return_value=updated)

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["move", "TB-1", "/new/path"])

        assert result.exit_code == 0
        assert "Moved worktree to:" in result.stdout
        assert "/new/path" in result.stdout

    def test_move_uncommitted_changes_error(self):
        entry = _make_entry()
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.move_worktree = AsyncMock(
            side_effect=UncommittedChangesError("uncommitted changes")
        )

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["move", "TB-1", "/new/path"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_move_worktree_not_found_error(self):
        entry = _make_entry()
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.move_worktree = AsyncMock(
            side_effect=WorktreeNotFoundError("not found")
        )

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["move", "TB-1", "/new/path"])

        assert result.exit_code == 1
        assert "Error" in result.output


# ---------------------------------------------------------------------------
# switch command
# ---------------------------------------------------------------------------


class TestSwitchCommand:
    def test_switch_not_found(self):
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = []
        mock_metadata.find_by_branch.return_value = None
        mock_metadata.find_by_path.return_value = None

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["switch", "nonexistent", "new-branch"])

        assert result.exit_code == 1
        assert "No worktree found" in result.output

    def test_switch_success(self):
        entry = _make_entry()
        updated = _make_entry(branch="feature/TB-2-other")
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.switch_branch = AsyncMock(return_value=updated)

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["switch", "TB-1", "feature/TB-2-other"])

        assert result.exit_code == 0
        assert "Switched to branch:" in result.stdout
        assert "feature/TB-2-other" in result.stdout

    def test_switch_branch_checked_out_error(self):
        entry = _make_entry()
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.switch_branch = AsyncMock(
            side_effect=BranchCheckedOutError("already checked out")
        )

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["switch", "TB-1", "some-branch"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_switch_invalid_input_error(self):
        entry = _make_entry()
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.switch_branch = AsyncMock(
            side_effect=InvalidInputError("branch not found")
        )

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["switch", "TB-1", "nonexistent-branch"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_switch_uncommitted_changes_error(self):
        entry = _make_entry()
        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.switch_branch = AsyncMock(
            side_effect=UncommittedChangesError("uncommitted changes")
        )

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["switch", "TB-1", "some-branch"])

        assert result.exit_code == 1
        assert "Error" in result.output


# ---------------------------------------------------------------------------
# prune command
# ---------------------------------------------------------------------------


class TestPruneCommand:
    def test_prune_dry_run(self):
        result = runner.invoke(app, ["prune"])
        assert result.exit_code == 0

    def test_prune_no_stale(self):
        mock_svc = MagicMock()
        mock_svc._discovery.discover_repos = AsyncMock(return_value=[])
        mock_svc._metadata.list_all.return_value = []
        mock_svc._config.resolve_worktrees_dir.return_value = Path("/nonexistent/path")

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["prune"])

        assert result.exit_code == 0
        assert "No stale references" in result.stdout

    def test_prune_apply_flag(self):
        mock_svc = MagicMock()
        mock_svc._discovery.discover_repos = AsyncMock(return_value=[])
        mock_svc._metadata.list_all.return_value = []
        mock_svc._config.resolve_worktrees_dir.return_value = Path("/nonexistent/path")

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            result = runner.invoke(app, ["prune", "--apply"])

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# _resolve_identifier helper
# ---------------------------------------------------------------------------


class TestResolveIdentifier:
    def test_resolve_by_issue_id(self):
        from gwt_worktree_manager.cli import _resolve_identifier

        entry = _make_entry(issue_id="TB-1")
        mock_metadata = MagicMock(spec=MetadataStore)
        mock_metadata.find_by_issue_id.return_value = [entry]

        result = _resolve_identifier(mock_metadata, "TB-1")
        assert result is entry

    def test_resolve_by_branch(self):
        from gwt_worktree_manager.cli import _resolve_identifier

        entry = _make_entry(branch="feature/TB-1-test")
        mock_metadata = MagicMock(spec=MetadataStore)
        mock_metadata.find_by_issue_id.return_value = []
        mock_metadata.find_by_branch.return_value = entry

        result = _resolve_identifier(mock_metadata, "feature/TB-1-test")
        assert result is entry

    def test_resolve_by_path(self):
        from gwt_worktree_manager.cli import _resolve_identifier

        entry = _make_entry(path="/some/path")
        mock_metadata = MagicMock(spec=MetadataStore)
        mock_metadata.find_by_issue_id.return_value = []
        mock_metadata.find_by_branch.return_value = None
        mock_metadata.find_by_path.return_value = entry

        result = _resolve_identifier(mock_metadata, "/some/path")
        assert result is entry

    def test_resolve_not_found(self):
        from gwt_worktree_manager.cli import _resolve_identifier

        mock_metadata = MagicMock(spec=MetadataStore)
        mock_metadata.find_by_issue_id.return_value = []
        mock_metadata.find_by_branch.return_value = None
        mock_metadata.find_by_path.return_value = None

        result = _resolve_identifier(mock_metadata, "unknown")
        assert result is None

    def test_resolve_multiple_matches_via_delete_command(self):
        """Multiple matches prompt is exercised via the delete command integration."""
        entry1 = _make_entry(id="id-1", repo_name="repo-a", issue_id="TB-1")
        entry2 = _make_entry(id="id-2", repo_name="repo-b", issue_id="TB-1")

        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry1, entry2]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata
        mock_svc.delete_worktree = AsyncMock(return_value=None)

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            # Select entry 1, then confirm deletion
            result = runner.invoke(app, ["delete", "TB-1"], input="1\ny\n")

        assert result.exit_code == 0
        assert "Multiple worktrees match" in result.output
        mock_svc.delete_worktree.assert_called_once_with("id-1", delete_branch=False)

    def test_resolve_multiple_matches_invalid_choice_via_delete(self):
        """Out-of-range choice returns None and exits with error."""
        entry1 = _make_entry(id="id-1", repo_name="repo-a", issue_id="TB-1")
        entry2 = _make_entry(id="id-2", repo_name="repo-b", issue_id="TB-1")

        mock_metadata = MagicMock()
        mock_metadata.find_by_issue_id.return_value = [entry1, entry2]

        mock_svc = MagicMock()
        mock_svc._metadata = mock_metadata

        with patch("gwt_worktree_manager.cli._get_service", return_value=mock_svc):
            # Choice 99 is out of range
            result = runner.invoke(app, ["delete", "TB-1"], input="99\n")

        assert result.exit_code == 1
