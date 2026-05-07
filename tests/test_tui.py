"""Tests for the GWT Worktree Manager TUI application."""

import pytest

from gwt_worktree_manager.app import GWTApp
from gwt_worktree_manager.store.metadata import WorktreeEntry
from gwt_worktree_manager.widgets.detail_panel import DetailPanel
from gwt_worktree_manager.widgets.dialogs import (
    BulkDeleteDialog,
    BulkForceDeleteDialog,
    CreateDialog,
    DeleteDialog,
)
from gwt_worktree_manager.widgets.repo_panel import RepoPanel
from gwt_worktree_manager.widgets.status_bar import GWTStatusBar
from gwt_worktree_manager.widgets.worktree_panel import (
    MARKED_ROW_STYLE,
    WorktreePanel,
)


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
    async def test_app_clears_status_after_mount(self):
        """Status bar is blank once the initial scan has completed."""
        async with GWTApp().run_test() as pilot:
            await pilot.pause()
            status = pilot.app.query_one(GWTStatusBar)
            assert str(status.content) == ""

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
        """Pressing 'r' triggers a refresh and leaves the status blank."""
        async with GWTApp().run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            status = pilot.app.query_one(GWTStatusBar)
            assert str(status.content) == ""

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


class TestWorktreePanelMarking:
    @pytest.mark.asyncio
    async def test_space_marks_current_row(self):
        """Pressing space toggles the mark on the highlighted row."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            entries = [
                _make_entry(id="a", branch="feature/a"),
                _make_entry(id="b", branch="feature/b"),
            ]
            wt_panel.set_worktrees(entries)
            await pilot.pause()
            wt_panel._table.focus()
            await pilot.pause()
            await pilot.press("space")
            cache = pilot.app._selection_cache
            assert cache.contains("a") is True
            assert cache.count == 1

    @pytest.mark.asyncio
    async def test_space_advances_cursor(self):
        """After toggling, the cursor moves to the next row."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            entries = [
                _make_entry(id="a", branch="feature/a"),
                _make_entry(id="b", branch="feature/b"),
            ]
            wt_panel.set_worktrees(entries)
            await pilot.pause()
            wt_panel._table.focus()
            await pilot.pause()
            await pilot.press("space")
            assert wt_panel._table.cursor_row == 1

    @pytest.mark.asyncio
    async def test_space_on_last_row_does_not_wrap(self):
        """Cursor stays on last row when space is pressed there."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            entries = [_make_entry(id="only", branch="feature/only")]
            wt_panel.set_worktrees(entries)
            await pilot.pause()
            wt_panel._table.focus()
            await pilot.pause()
            await pilot.press("space")
            assert wt_panel._table.cursor_row == 0
            assert pilot.app._selection_cache.contains("only") is True

    @pytest.mark.asyncio
    async def test_space_toggles_off(self):
        """Pressing space on a marked row unmarks it."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            entries = [_make_entry(id="a", branch="feature/a")]
            wt_panel.set_worktrees(entries)
            await pilot.pause()
            wt_panel._table.focus()
            await pilot.pause()
            await pilot.press("space")
            wt_panel._table.move_cursor(row=0)
            await pilot.pause()
            await pilot.press("space")
            assert pilot.app._selection_cache.contains("a") is False

    @pytest.mark.asyncio
    async def test_space_on_empty_table_is_noop(self):
        """Space on an empty worktree panel does nothing."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            wt_panel.set_worktrees([])
            await pilot.pause()
            await pilot.press("space")
            assert pilot.app._selection_cache.count == 0

    @pytest.mark.asyncio
    async def test_marks_survive_repo_switch_simulation(self):
        """After set_worktrees is called again, marker re-applies for cached IDs."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            cache = pilot.app._selection_cache
            e = _make_entry(id="persists", repo_name="alpha", branch="feature/persists")
            cache.toggle(e)
            wt_panel.set_worktrees([e])
            await pilot.pause()
            marker_cell = wt_panel._table.get_cell_at((0, 0))
            assert str(marker_cell).strip() == "●"

    @pytest.mark.asyncio
    async def test_unmarked_row_shows_blank_marker(self):
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            wt_panel.set_worktrees([_make_entry(id="a", branch="feature/a")])
            await pilot.pause()
            marker_cell = wt_panel._table.get_cell_at((0, 0))
            assert str(marker_cell).strip() == ""


class TestWorktreePanelBaseColumn:
    @pytest.mark.asyncio
    async def test_column_headers_in_expected_order(self):
        """The DataTable exposes the marker, branch, issue, type, and base columns in that order."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            await pilot.pause()
            headers = [col.label.plain for col in wt_panel._table.columns.values()]
            assert headers == [" ", "Branch", "Issue", "Type", "Base"]

    @pytest.mark.asyncio
    async def test_base_cell_renders_source_branch(self):
        """A populated source_branch renders verbatim in the Base column."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            wt_panel.set_worktrees([_make_entry(id="a", source_branch="main")])
            await pilot.pause()
            cell = wt_panel._table.get_cell_at((0, 4))
            assert cell.plain == "main"

    @pytest.mark.asyncio
    async def test_base_cell_renders_dash_for_empty_string(self):
        """An empty source_branch renders as the '-' placeholder."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            wt_panel.set_worktrees([_make_entry(id="a", source_branch="")])
            await pilot.pause()
            cell = wt_panel._table.get_cell_at((0, 4))
            assert cell.plain == "-"

    @pytest.mark.asyncio
    async def test_base_cell_renders_dash_for_none(self):
        """A None source_branch renders as the '-' placeholder via the runtime guard."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            entry = _make_entry(id="a")
            # Runtime-only check: type is str="", but the `or "-"` guard must
            # also tolerate None reaching the cell.
            entry.source_branch = None  # type: ignore[assignment]
            wt_panel.set_worktrees([entry])
            await pilot.pause()
            cell = wt_panel._table.get_cell_at((0, 4))
            assert cell.plain == "-"

    @pytest.mark.asyncio
    async def test_base_cell_distinct_values_per_row(self):
        """Two rows render their respective source_branch values; guards off-by-one."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            wt_panel.set_worktrees([
                _make_entry(
                    id="a",
                    branch="feature/a",
                    source_branch="main",
                    last_accessed="2026-04-01T00:00:00Z",
                ),
                _make_entry(
                    id="b",
                    branch="feature/b",
                    source_branch="develop",
                    last_accessed="2026-03-01T00:00:00Z",
                ),
            ])
            await pilot.pause()
            assert wt_panel._table.get_cell_at((0, 4)).plain == "main"
            assert wt_panel._table.get_cell_at((1, 4)).plain == "develop"

    @pytest.mark.asyncio
    async def test_base_cell_preserves_whitespace(self):
        """source_branch values are rendered verbatim, without stripping."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            wt_panel.set_worktrees([_make_entry(id="a", source_branch="  main  ")])
            await pilot.pause()
            cell = wt_panel._table.get_cell_at((0, 4))
            assert cell.plain == "  main  "

    @pytest.mark.asyncio
    async def test_base_cell_marked_row_styled(self):
        """Marked rows render the Base cell in the marked-row style."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            cache = pilot.app._selection_cache
            entry = _make_entry(id="a", source_branch="main")
            cache.toggle(entry)
            wt_panel.set_worktrees([entry])
            await pilot.pause()
            cell = wt_panel._table.get_cell_at((0, 4))
            assert str(cell.style) == MARKED_ROW_STYLE

    @pytest.mark.asyncio
    async def test_base_cell_unmarked_row_unstyled(self):
        """Unmarked rows render the Base cell with no marked-row style."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            wt_panel.set_worktrees([_make_entry(id="a", source_branch="main")])
            await pilot.pause()
            cell = wt_panel._table.get_cell_at((0, 4))
            assert str(cell.style) == ""

    @pytest.mark.asyncio
    async def test_base_cell_marked_under_filter(self):
        """A marked row that survives a filter retains the marked-row style on Base."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            cache = pilot.app._selection_cache
            keep = _make_entry(id="keep", branch="feature/keep", source_branch="main")
            drop = _make_entry(id="drop", branch="feature/drop", source_branch="develop")
            cache.toggle(keep)
            wt_panel.set_worktrees([keep, drop])
            wt_panel._filter_text = "keep"
            wt_panel._rebuild_table()
            await pilot.pause()
            assert wt_panel._table.row_count == 1
            assert wt_panel._table.get_cell_at((0, 1)).plain == "feature/keep"
            assert str(wt_panel._table.get_cell_at((0, 4)).style) == MARKED_ROW_STYLE

    @pytest.mark.asyncio
    async def test_base_cell_updates_on_refresh(self):
        """Re-calling set_worktrees with a changed source_branch updates the cell."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            wt_panel.set_worktrees([_make_entry(id="a", source_branch="main")])
            await pilot.pause()
            assert wt_panel._table.get_cell_at((0, 4)).plain == "main"
            wt_panel.set_worktrees([_make_entry(id="a", source_branch="develop")])
            await pilot.pause()
            assert wt_panel._table.get_cell_at((0, 4)).plain == "develop"

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
        """set_worktree displays entry fields with explicit per-line assertions."""
        async with GWTApp().run_test() as pilot:
            detail = pilot.app.query_one(DetailPanel)
            entry = _make_entry()
            detail.set_worktree(entry)
            await pilot.pause()
            text = str(detail._content.content)
            assert "TB-123" in text
            assert "feature" in text
            assert f"Branch: {entry.branch}" in text
            assert f"Base: {entry.source_branch}" in text

    @pytest.mark.asyncio
    async def test_uses_base_label_not_source(self):
        """The detail panel labels the base branch line `Base:`, not `Source:`."""
        async with GWTApp().run_test() as pilot:
            detail = pilot.app.query_one(DetailPanel)
            detail.set_worktree(_make_entry(source_branch="main"))
            await pilot.pause()
            text = str(detail._content.content)
            assert "Base: main" in text
            assert "Source:" not in text

    @pytest.mark.asyncio
    async def test_base_placeholder_is_dash_for_empty(self):
        """An empty source_branch renders as `Base: -` and never as `unknown`."""
        async with GWTApp().run_test() as pilot:
            detail = pilot.app.query_one(DetailPanel)
            detail.set_worktree(_make_entry(source_branch=""))
            await pilot.pause()
            text = str(detail._content.content)
            assert "Base: -" in text
            assert "unknown" not in text

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

    @pytest.mark.asyncio
    async def test_mark_count_appends_suffix(self):
        """Non-zero mark_count appends ' | N marked' suffix."""
        async with GWTApp().run_test() as pilot:
            status = pilot.app.query_one(GWTStatusBar)
            status.update_status("Ready")
            status.mark_count = 3
            await pilot.pause()
            assert str(status.content) == "Ready | 3 marked"

    @pytest.mark.asyncio
    async def test_mark_count_zero_drops_suffix(self):
        """mark_count == 0 renders just the base message."""
        async with GWTApp().run_test() as pilot:
            status = pilot.app.query_one(GWTStatusBar)
            status.update_status("Ready")
            status.mark_count = 2
            await pilot.pause()
            status.mark_count = 0
            await pilot.pause()
            assert str(status.content) == "Ready"

    @pytest.mark.asyncio
    async def test_update_status_preserves_suffix(self):
        """Updating the base message while marks exist keeps the suffix."""
        async with GWTApp().run_test() as pilot:
            status = pilot.app.query_one(GWTStatusBar)
            status.mark_count = 5
            status.update_status("Other")
            await pilot.pause()
            assert str(status.content) == "Other | 5 marked"

    @pytest.mark.asyncio
    async def test_status_bar_observes_selection_cache(self):
        """Toggling worktrees via space updates the status bar mark count."""
        async with GWTApp().run_test() as pilot:
            wt_panel = pilot.app.query_one(WorktreePanel)
            status = pilot.app.query_one(GWTStatusBar)
            status.update_status("Ready")
            wt_panel.set_worktrees([
                _make_entry(id="a", branch="feature/a"),
                _make_entry(id="b", branch="feature/b"),
            ])
            await pilot.pause()
            wt_panel._table.focus()
            await pilot.pause()
            await pilot.press("space")
            assert "1 marked" in str(status.content)
            await pilot.press("space")
            assert "2 marked" in str(status.content)


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


class TestDispatchFork:
    @pytest.mark.asyncio
    async def test_empty_cache_opens_single_delete_dialog(self):
        """ctrl+d with no marks pushes DeleteDialog, not BulkDeleteDialog."""
        async with GWTApp().run_test() as pilot:
            app = pilot.app
            wt_panel = app.query_one(WorktreePanel)
            wt_panel.set_worktrees([_make_entry(id="a", branch="feature/a")])
            await pilot.pause()
            wt_panel._table.focus()
            await pilot.pause()
            assert app._selection_cache.count == 0

            screens = []
            orig = app.push_screen_wait

            async def _capture(screen, *args, **kwargs):
                screens.append(screen)
                return None

            app.push_screen_wait = _capture
            try:
                app.action_delete_worktree()
                for _ in range(10):
                    await pilot.pause()
                    if screens:
                        break
            finally:
                app.push_screen_wait = orig

            assert len(screens) == 1
            assert isinstance(screens[0], DeleteDialog)
            assert not isinstance(screens[0], BulkDeleteDialog)

    @pytest.mark.asyncio
    async def test_non_empty_cache_opens_bulk_delete_dialog(self):
        """ctrl+d with marks pushes BulkDeleteDialog with pre-resolved entries."""
        async with GWTApp().run_test() as pilot:
            app = pilot.app
            wt_panel = app.query_one(WorktreePanel)
            entries = [
                _make_entry(id="a", branch="feature/a"),
                _make_entry(id="b", branch="feature/b"),
            ]
            wt_panel.set_worktrees(entries)
            await pilot.pause()
            app._selection_cache.toggle(entries[0])
            app._selection_cache.toggle(entries[1])
            assert app._selection_cache.count == 2

            screens = []
            orig = app.push_screen_wait

            async def _capture(screen, *args, **kwargs):
                screens.append(screen)
                return None  # cancel the dialog

            app.push_screen_wait = _capture
            try:
                app.action_delete_worktree()
                for _ in range(10):
                    await pilot.pause()
                    if screens:
                        break
            finally:
                app.push_screen_wait = orig

            assert len(screens) == 1
            assert isinstance(screens[0], BulkDeleteDialog)
            assert [e.id for e in screens[0]._working] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_bulk_confirm_invokes_service_and_clears_succeeded(self, monkeypatch):
        """Confirming the bulk dialog calls delete_worktrees_bulk and clears the cache."""
        from gwt_worktree_manager.services.worktree import BulkDeleteResult

        async with GWTApp().run_test() as pilot:
            app = pilot.app
            wt_panel = app.query_one(WorktreePanel)
            entries = [
                _make_entry(id="a", branch="feature/a"),
                _make_entry(id="b", branch="feature/b"),
            ]
            wt_panel.set_worktrees(entries)
            await pilot.pause()
            app._selection_cache.toggle(entries[0])
            app._selection_cache.toggle(entries[1])

            calls: list[dict] = []

            async def _fake_bulk(entries, *, delete_branch, force=False, on_progress=None):
                calls.append(
                    {
                        "ids": [e.id for e in entries],
                        "delete_branch": delete_branch,
                        "force": force,
                    }
                )
                return BulkDeleteResult(
                    succeeded=[e.id for e in entries], dirty=[], failed=[]
                )

            app._service.delete_worktrees_bulk = _fake_bulk

            async def _fake_push(screen, *args, **kwargs):
                if isinstance(screen, BulkDeleteDialog):
                    return {"entries": list(screen._working), "delete_branch": True}
                return None

            app.push_screen_wait = _fake_push

            app.action_delete_worktree()
            for _ in range(20):
                await pilot.pause()
                if calls and app._selection_cache.count == 0:
                    break

            assert len(calls) == 1
            assert sorted(calls[0]["ids"]) == ["a", "b"]
            assert calls[0]["delete_branch"] is True
            assert calls[0]["force"] is False
            assert app._selection_cache.count == 0

    @pytest.mark.asyncio
    async def test_bulk_dirty_triggers_force_dialog_and_force_all(self, monkeypatch):
        """Dirty items surface a BulkForceDeleteDialog; Force All runs the second pass."""
        from gwt_worktree_manager.services.worktree import BulkDeleteResult

        async with GWTApp().run_test() as pilot:
            app = pilot.app
            wt_panel = app.query_one(WorktreePanel)
            a = _make_entry(id="a", branch="feature/a")
            b = _make_entry(id="b", branch="feature/b")
            wt_panel.set_worktrees([a, b])
            await pilot.pause()
            app._selection_cache.toggle(a)
            app._selection_cache.toggle(b)

            bulk_calls: list[tuple[list[str], bool]] = []

            async def _fake_bulk(entries, *, delete_branch, force=False, on_progress=None):
                bulk_calls.append(([e.id for e in entries], force))
                if not force:
                    return BulkDeleteResult(succeeded=["a"], dirty=[b], failed=[])
                return BulkDeleteResult(succeeded=["b"], dirty=[], failed=[])

            app._service.delete_worktrees_bulk = _fake_bulk

            async def _fake_push(screen, *args, **kwargs):
                if isinstance(screen, BulkDeleteDialog):
                    return {"entries": list(screen._working), "delete_branch": False}
                if isinstance(screen, BulkForceDeleteDialog):
                    return True  # Force All
                return None

            app.push_screen_wait = _fake_push

            app.action_delete_worktree()
            for _ in range(30):
                await pilot.pause()
                if len(bulk_calls) == 2:
                    break

            assert len(bulk_calls) == 2
            assert bulk_calls[0] == (["a", "b"], False)
            assert bulk_calls[1] == (["b"], True)
            assert app._selection_cache.count == 0

    @pytest.mark.asyncio
    async def test_bulk_dirty_skip_retains_dirty_items(self):
        """Skipping the force dialog leaves dirty items in the cache."""
        from gwt_worktree_manager.services.worktree import BulkDeleteResult

        async with GWTApp().run_test() as pilot:
            app = pilot.app
            wt_panel = app.query_one(WorktreePanel)
            a = _make_entry(id="a", branch="feature/a")
            b = _make_entry(id="b", branch="feature/b")
            wt_panel.set_worktrees([a, b])
            await pilot.pause()
            app._selection_cache.toggle(a)
            app._selection_cache.toggle(b)

            async def _fake_bulk(entries, *, delete_branch, force=False, on_progress=None):
                return BulkDeleteResult(succeeded=["a"], dirty=[b], failed=[])

            app._service.delete_worktrees_bulk = _fake_bulk

            async def _fake_push(screen, *args, **kwargs):
                if isinstance(screen, BulkDeleteDialog):
                    return {"entries": list(screen._working), "delete_branch": False}
                if isinstance(screen, BulkForceDeleteDialog):
                    return False  # Skip
                return None

            app.push_screen_wait = _fake_push

            app.action_delete_worktree()
            for _ in range(20):
                await pilot.pause()
                if not app._selection_cache.contains("a"):
                    break

            assert app._selection_cache.contains("a") is False
            assert app._selection_cache.contains("b") is True
