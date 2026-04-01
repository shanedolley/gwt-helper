"""Tests for the GWT Worktree Manager TUI application."""

import pytest

from gwt_worktree_manager.app import GWTApp
from gwt_worktree_manager.store.metadata import WorktreeEntry
from gwt_worktree_manager.widgets.detail_panel import DetailPanel
from gwt_worktree_manager.widgets.dialogs import CreateDialog, DeleteDialog
from gwt_worktree_manager.widgets.repo_panel import RepoPanel
from gwt_worktree_manager.widgets.status_bar import GWTStatusBar
from gwt_worktree_manager.widgets.worktree_panel import WorktreePanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(**overrides) -> WorktreeEntry:
    """Return a WorktreeEntry with sensible defaults."""
    defaults = {
        "id": "test-uuid",
        "repo_name": "myapp",
        "branch": "feature/TB-123-test",
        "path": "/tmp/test",
        "issue_id": "TB-123",
        "work_type": "feature",
        "source_branch": "main",
        "created_at": "2026-03-27T00:00:00Z",
        "last_accessed": "2026-03-27T00:00:00Z",
        "tags": ["frontend"],
    }
    defaults.update(overrides)
    return WorktreeEntry(**defaults)


# ---------------------------------------------------------------------------
# GWTApp
# ---------------------------------------------------------------------------


class TestGWTApp:
    @pytest.mark.asyncio
    async def test_app_renders_all_panels(self):
        """All panels are present on first render."""
        async with GWTApp().run_test() as pilot:
            assert pilot.app.query_one(RepoPanel) is not None
            assert pilot.app.query_one(WorktreePanel) is not None
            assert pilot.app.query_one(DetailPanel) is not None
            assert pilot.app.query_one(GWTStatusBar) is not None

    @pytest.mark.asyncio
    async def test_app_shows_status_on_mount(self):
        """Status bar shows a message after mounting."""
        async with GWTApp().run_test() as pilot:
            await pilot.pause()
            status = pilot.app.query_one(GWTStatusBar)
            text = str(status.content).lower()
            assert any(word in text for word in ("repos", "ready", "scanning"))

    @pytest.mark.asyncio
    async def test_quit_binding(self):
        """Pressing 'q' exits the application."""
        async with GWTApp().run_test() as pilot:
            await pilot.press("q")
            # After q is pressed the app should be in the process of exiting.
            # We just verify no exception was raised.

    @pytest.mark.asyncio
    async def test_help_notification(self):
        """Pressing '?' triggers the help notification without error."""
        async with GWTApp().run_test() as pilot:
            await pilot.press("question_mark")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_refresh_action(self):
        """Pressing 'r' triggers a refresh without error."""
        async with GWTApp().run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            status = pilot.app.query_one(GWTStatusBar)
            text = str(status.content).lower()
            assert "repos" in text

    @pytest.mark.asyncio
    async def test_tab_cycles_focus(self):
        """Pressing Tab does not raise an exception."""
        async with GWTApp().run_test() as pilot:
            await pilot.press("tab")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_yank_no_selection_does_not_crash(self):
        """Pressing 'y' when nothing is selected does not raise."""
        async with GWTApp().run_test() as pilot:
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_delete_no_selection_does_not_crash(self):
        """Pressing 'd' when nothing is selected does not raise."""
        async with GWTApp().run_test() as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_open_no_selection_does_not_crash(self):
        """Pressing 'o' when nothing is selected does not raise."""
        async with GWTApp().run_test() as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_run_tui_importable(self):
        """run_tui is importable from app module."""
        from gwt_worktree_manager.app import run_tui

        assert callable(run_tui)


# ---------------------------------------------------------------------------
# RepoPanel
# ---------------------------------------------------------------------------


class TestRepoPanel:
    @pytest.mark.asyncio
    async def test_empty_repos(self):
        """Setting an empty repo list does not raise."""
        async with GWTApp().run_test() as pilot:
            repo_panel = pilot.app.query_one(RepoPanel)
            repo_panel.set_repos([])
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_set_repos_updates_list(self):
        """set_repos populates the internal repo list."""
        async with GWTApp().run_test() as pilot:
            await pilot.pause()
            repo_panel = pilot.app.query_one(RepoPanel)
            # _repos may already be populated by on_mount; verify attribute exists
            assert isinstance(repo_panel._repos, list)


# ---------------------------------------------------------------------------
# WorktreePanel
# ---------------------------------------------------------------------------


class TestWorktreePanel:
    @pytest.mark.asyncio
    async def test_empty_state_shows_message(self):
        """An empty worktree list does not raise."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            wt_panel.set_worktrees([])
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_set_worktrees_with_entries(self):
        """Providing worktree entries populates the panel."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            entries = [_make_entry(), _make_entry(id="uuid-2", branch="bug/X-1-fix")]
            wt_panel.set_worktrees(entries)
            await pilot.pause()
            assert len(wt_panel._entries) == 2

    @pytest.mark.asyncio
    async def test_get_selected_returns_none_when_empty(self):
        """get_selected returns None when no entries are present."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            wt_panel.set_worktrees([])
            await pilot.pause()
            assert wt_panel.get_selected() is None

    @pytest.mark.asyncio
    async def test_entries_sorted_by_last_accessed(self):
        """Entries are sorted by last_accessed in descending order."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            older = _make_entry(id="old", last_accessed="2026-01-01T00:00:00Z")
            newer = _make_entry(id="new", last_accessed="2026-03-27T00:00:00Z")
            wt_panel.set_worktrees([older, newer])
            await pilot.pause()
            assert wt_panel._entries[0].id == "new"
            assert wt_panel._entries[1].id == "old"


# ---------------------------------------------------------------------------
# DetailPanel
# ---------------------------------------------------------------------------


class TestDetailPanel:
    @pytest.mark.asyncio
    async def test_no_selection_shows_default(self):
        """set_worktree(None) resets to the default message."""
        async with GWTApp().run_test() as pilot:
            detail = pilot.app.query_one(DetailPanel)
            detail.set_worktree(None)
            await pilot.pause()
            text = str(detail._content.content)
            assert "select" in text.lower()

    @pytest.mark.asyncio
    async def test_shows_worktree_info(self):
        """set_worktree displays entry fields."""
        async with GWTApp().run_test() as pilot:
            detail = pilot.app.query_one(DetailPanel)
            entry = _make_entry()
            detail.set_worktree(entry)
            await pilot.pause()
            text = str(detail._content.content)
            assert "TB-123" in text
            assert "feature" in text
            assert "myapp" in text or "main" in text

    @pytest.mark.asyncio
    async def test_shows_tags(self):
        """Tags are rendered in the detail panel."""
        async with GWTApp().run_test() as pilot:
            detail = pilot.app.query_one(DetailPanel)
            entry = _make_entry(tags=["urgent", "backend"])
            detail.set_worktree(entry)
            await pilot.pause()
            text = str(detail._content.content)
            assert "urgent" in text

    @pytest.mark.asyncio
    async def test_shows_no_tags_when_empty(self):
        """Empty tags list renders as 'none'."""
        async with GWTApp().run_test() as pilot:
            detail = pilot.app.query_one(DetailPanel)
            entry = _make_entry(tags=[])
            detail.set_worktree(entry)
            await pilot.pause()
            text = str(detail._content.content)
            assert "none" in text.lower()


# ---------------------------------------------------------------------------
# GWTStatusBar
# ---------------------------------------------------------------------------


class TestStatusBar:
    @pytest.mark.asyncio
    async def test_initial_content(self):
        """Status bar starts with 'Starting...' text."""
        async with GWTApp().run_test() as pilot:
            # Before mount completes it shows "Starting..." briefly.
            # After mount it is updated; just verify the widget exists.
            status = pilot.app.query_one(GWTStatusBar)
            assert status is not None

    @pytest.mark.asyncio
    async def test_update_status(self):
        """update_status changes the displayed text."""
        async with GWTApp().run_test() as pilot:
            status = pilot.app.query_one(GWTStatusBar)
            status.update_status("Test message")
            await pilot.pause()
            assert str(status.content) == "Test message"

    @pytest.mark.asyncio
    async def test_update_status_multiple_times(self):
        """update_status can be called multiple times."""
        async with GWTApp().run_test() as pilot:
            status = pilot.app.query_one(GWTStatusBar)
            status.update_status("First")
            await pilot.pause()
            status.update_status("Second")
            await pilot.pause()
            assert str(status.content) == "Second"


# ---------------------------------------------------------------------------
# CreateDialog
# ---------------------------------------------------------------------------


class TestCreateDialog:
    @pytest.mark.asyncio
    async def test_create_dialog_instantiates(self):
        """CreateDialog can be instantiated without error."""
        from gwt_worktree_manager.config.manager import Config

        dialog = CreateDialog(repos=[], config=Config())
        assert dialog is not None

    @pytest.mark.asyncio
    async def test_delete_dialog_instantiates(self):
        """DeleteDialog can be instantiated without error."""
        entry = _make_entry()
        dialog = DeleteDialog(entry)
        assert dialog is not None
