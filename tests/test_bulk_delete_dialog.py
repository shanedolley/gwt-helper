"""Tests for BulkDeleteDialog and BulkForceDeleteDialog."""

import pytest
from textual import work
from textual.app import App

from gwt_worktree_manager.store.metadata import WorktreeEntry
from gwt_worktree_manager.widgets.dialogs import BulkDeleteDialog, BulkForceDeleteDialog


def _entry(id: str, repo: str = "myapp", branch: str = "") -> WorktreeEntry:
    return WorktreeEntry(
        id=id,
        repo_name=repo,
        branch=branch or f"feature/{id}",
        path=f"/tmp/{id}",
    )


class _DialogHost(App):
    """Minimal host app for pushing a modal dialog in tests."""

    def __init__(self, dialog):
        super().__init__()
        self._dialog = dialog
        self.result = None

    def on_mount(self) -> None:
        self._show()

    @work
    async def _show(self) -> None:
        self.result = await self.push_screen_wait(self._dialog)


class TestBulkDeleteDialog:
    @pytest.mark.asyncio
    async def test_header_counts_worktrees_and_repos(self):
        entries = [
            _entry("a", repo="alpha"),
            _entry("b", repo="beta"),
            _entry("c", repo="alpha"),
        ]
        dialog = BulkDeleteDialog(entries)
        host = _DialogHost(dialog)
        async with host.run_test() as pilot:
            await pilot.pause()
            header = str(dialog.query_one("#bulk-header").content)
            assert "3 worktrees across 2 repos" in header
            await pilot.press("escape")

    @pytest.mark.asyncio
    async def test_cancel_returns_none(self):
        entries = [_entry("a")]
        dialog = BulkDeleteDialog(entries)
        host = _DialogHost(dialog)
        async with host.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        assert host.result is None

    @pytest.mark.asyncio
    async def test_confirm_returns_working_list_and_flag(self):
        entries = [_entry("a"), _entry("b")]
        dialog = BulkDeleteDialog(entries)
        host = _DialogHost(dialog)
        async with host.run_test() as pilot:
            await pilot.pause()
            dialog.query_one("#bulk-delete-branch").value = True
            await pilot.click("#btn-bulk-confirm")
            await pilot.pause()
        assert host.result is not None
        assert [e.id for e in host.result["entries"]] == ["a", "b"]
        assert host.result["delete_branch"] is True

    @pytest.mark.asyncio
    async def test_x_removes_highlighted_row(self):
        entries = [_entry("a"), _entry("b"), _entry("c")]
        dialog = BulkDeleteDialog(entries)
        host = _DialogHost(dialog)
        async with host.run_test() as pilot:
            await pilot.pause()
            table = dialog.query_one("#bulk-list")
            table.focus()
            await pilot.pause()
            table.move_cursor(row=1)
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            assert [e.id for e in dialog._working] == ["a", "c"]
            header = str(dialog.query_one("#bulk-header").content)
            assert "2 worktrees" in header
            await pilot.press("escape")

    @pytest.mark.asyncio
    async def test_confirm_disabled_when_working_empty(self):
        entries = [_entry("a")]
        dialog = BulkDeleteDialog(entries)
        host = _DialogHost(dialog)
        async with host.run_test() as pilot:
            await pilot.pause()
            table = dialog.query_one("#bulk-list")
            table.focus()
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            confirm = dialog.query_one("#btn-bulk-confirm")
            assert confirm.disabled is True
            await pilot.press("escape")

    @pytest.mark.asyncio
    async def test_input_list_not_mutated_by_x(self):
        entries = [_entry("a"), _entry("b")]
        dialog = BulkDeleteDialog(entries)
        host = _DialogHost(dialog)
        async with host.run_test() as pilot:
            await pilot.pause()
            table = dialog.query_one("#bulk-list")
            table.focus()
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            assert [e.id for e in entries] == ["a", "b"]
            await pilot.press("escape")


class TestBulkForceDeleteDialog:
    @pytest.mark.asyncio
    async def test_force_returns_true(self):
        entries = [_entry("dirty1"), _entry("dirty2")]
        dialog = BulkForceDeleteDialog(entries)
        host = _DialogHost(dialog)
        async with host.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-force-all")
            await pilot.pause()
        assert host.result is True

    @pytest.mark.asyncio
    async def test_skip_returns_false(self):
        entries = [_entry("dirty1")]
        dialog = BulkForceDeleteDialog(entries)
        host = _DialogHost(dialog)
        async with host.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-force-skip")
            await pilot.pause()
        assert host.result is False

    @pytest.mark.asyncio
    async def test_escape_returns_false(self):
        entries = [_entry("dirty1")]
        dialog = BulkForceDeleteDialog(entries)
        host = _DialogHost(dialog)
        async with host.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        assert host.result is False

    @pytest.mark.asyncio
    async def test_header_includes_count(self):
        entries = [_entry("a"), _entry("b"), _entry("c")]
        dialog = BulkForceDeleteDialog(entries)
        host = _DialogHost(dialog)
        async with host.run_test() as pilot:
            await pilot.pause()
            header = str(dialog.query_one("#force-header").content)
            assert "3" in header
            await pilot.press("escape")
