"""Textual TUI application for GWT Worktree Manager."""

import asyncio
import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import Provider, Hit, Hits
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header
from textual import work

from gwt_worktree_manager.config.manager import load_config
from gwt_worktree_manager.git import operations as git
from gwt_worktree_manager.services.discovery import RepoDiscovery
from gwt_worktree_manager.services.hooks import HookRunner
from gwt_worktree_manager.services.terminal import TerminalOpener
from gwt_worktree_manager.services.worktree import (
    BulkDeleteResult,
    UncommittedChangesError,
    WorktreeService,
)
from gwt_worktree_manager.state.selection_cache import SelectionCache
from gwt_worktree_manager.store.metadata import MetadataStore, WorktreeEntry
from gwt_worktree_manager.store.ui_state import UIStateStore
from gwt_worktree_manager.widgets.detail_panel import DetailPanel
from gwt_worktree_manager.widgets.dialogs import (
    BulkDeleteDialog,
    BulkForceDeleteDialog,
    CreateDialog,
    DeleteDialog,
    ForceDeleteDialog,
)
from gwt_worktree_manager.widgets.repo_panel import RepoPanel
from gwt_worktree_manager.widgets.splitter import SplitterBar
from gwt_worktree_manager.widgets.status_bar import GWTStatusBar
from gwt_worktree_manager.widgets.worktree_panel import WorktreePanel


class GWTCommands(Provider):
    """Provide GWT actions to the command palette."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        commands = [
            ("Create Worktree", "create"),
            ("Delete Worktree", "delete_worktree"),
            ("Open Worktree", "open_worktree"),
            ("Refresh", "refresh"),
            ("Copy Path", "yank"),
            ("Open Issue URL", "open_issue_url"),
            ("Edit in Editor", "edit_worktree"),
        ]
        for name, action in commands:
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    lambda a=action: self.app.run_action(a),
                )


class GWTApp(App):
    """GWT Worktree Manager TUI Application."""

    TITLE = "GWT Worktree Manager"
    COMMANDS = App.COMMANDS | {GWTCommands}

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-area {
        height: 1fr;
    }

    #left-panel {
        width: 30;
    }

    #right-panel {
        width: 1fr;
    }

    RepoPanel {
        height: 100%;
        border: solid $accent;
    }

    RepoPanel:focus-within {
        border: double $accent;
    }

    WorktreePanel {
        height: 1fr;
        border: solid $primary;
    }

    WorktreePanel:focus-within {
        border: double $primary;
    }

    DetailPanel {
        height: auto;
        min-height: 6;
        max-height: 12;
        border: solid $secondary;
    }

    GWTStatusBar {
        height: 1;
        background: $surface;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", key_display="ctrl+q"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("ctrl+n", "create", "New", key_display="ctrl+n"),
        Binding("ctrl+d", "delete_worktree", "Delete", key_display="ctrl+d"),
        Binding("ctrl+o", "open_worktree", "Open", key_display="ctrl+o"),
        Binding("ctrl+r", "refresh", "Refresh", key_display="ctrl+r"),
        Binding("ctrl+y", "yank", "Copy Path", key_display="ctrl+y"),
        Binding("tab", "focus_next_panel", "Next Panel"),
        Binding("ctrl+m", "move_worktree", "Move", key_display="ctrl+m"),
        Binding("ctrl+s", "switch_worktree", "Switch", key_display="ctrl+s"),
        Binding("ctrl+u", "open_issue_url", "Open URL", key_display="ctrl+u"),
        Binding("ctrl+e", "edit_worktree", "Edit", key_display="ctrl+e"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config = load_config()
        self._metadata = MetadataStore()
        self._ui_state = UIStateStore()
        self._discovery = RepoDiscovery(self._config)
        self._service = WorktreeService(self._config, self._metadata, self._discovery)
        self._hook_runner = HookRunner(self._config)
        self._terminal_opener = TerminalOpener(
            terminal=self._config.terminal,
            ai_assistant=self._config.ai_assistant,
        )
        self._repos: list = []
        self._selected_repo = None
        self._selection_cache = SelectionCache()
        self._delete_in_progress = False

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()
        with Horizontal(id="main-area"):
            with Vertical(id="left-panel"):
                yield RepoPanel(id="repo-panel")
            yield SplitterBar(direction="horizontal", id="h-splitter")
            with Vertical(id="right-panel"):
                yield WorktreePanel(
                    selection_cache=self._selection_cache,
                    id="worktree-panel",
                )
                yield DetailPanel(id="detail-panel")
        yield GWTStatusBar(id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Load data after the app mounts."""
        # Apply saved pane sizes
        self.query_one("#left-panel").styles.width = self._ui_state.left_panel_width

        status = self.query_one(GWTStatusBar)

        def _sync_mark_count(count: int) -> None:
            status.mark_count = count

        self._selection_cache.on_change(_sync_mark_count)

        status.update_status("Scanning repos...")

        self._repos = await self._discovery.discover_repos()
        repo_panel = self.query_one(RepoPanel)
        repo_panel.set_repos(self._repos)

        for repo in self._repos:
            try:
                worktrees = await git.list_worktrees(repo.path)
                self._metadata.reconcile(worktrees, repo_name=repo.name)
            except Exception:
                pass

        status.update_status("")
        repo_panel.focus_tree()

    async def on_repo_panel_repo_selected(self, event: RepoPanel.RepoSelected) -> None:
        """Handle repo selection from the repo panel."""
        self._selected_repo = event.repo
        worktree_panel = self.query_one(WorktreePanel)
        entries = await self._service.list_worktrees(repo_name=event.repo.name)
        worktree_panel.set_worktrees(entries)

    async def on_repo_panel_repo_confirmed(self, event: RepoPanel.RepoConfirmed) -> None:
        """Handle Enter on a repo — focus the worktree panel."""
        worktree_panel = self.query_one(WorktreePanel)
        if worktree_panel._table is not None:
            worktree_panel._table.focus()

    def on_splitter_bar_resized(self, event: SplitterBar.Resized) -> None:
        """Handle pane resize during splitter drag."""
        if event.splitter.id == "h-splitter":
            left = self.query_one("#left-panel")
            new_width = left.size.width + event.delta
            new_width = max(15, min(80, new_width))
            left.styles.width = new_width
            self._ui_state.left_panel_width = new_width

    def on_splitter_bar_resize_complete(self, event: SplitterBar.ResizeComplete) -> None:
        """Save pane sizes when drag finishes."""
        self._ui_state.save()

    async def on_worktree_panel_worktree_selected(
        self, event: WorktreePanel.WorktreeSelected
    ) -> None:
        """Handle worktree selection from the worktree panel."""
        detail_panel = self.query_one(DetailPanel)
        detail_panel.set_worktree(event.entry)

    @work
    async def action_create(self) -> None:
        """Open the create worktree dialog."""
        selected_name = self._selected_repo.name if self._selected_repo else None
        dialog = CreateDialog(self._repos, self._config, default_repo=selected_name)
        result = await self.push_screen_wait(dialog)
        if result:
            status = self.query_one(GWTStatusBar)
            status.update_status("Creating worktree...")
            try:
                if result.get("work_type") == "pr-review":
                    entry = await self._service.create_pr_review_worktree(
                        repo_name=result["repo_name"],
                        pr_number=result["pr_number"],
                    )
                else:
                    entry = await self._service.create_worktree(**result)
                status.update_status("Running hooks...")
                await self._hook_runner.run_post_create_hooks(
                    entry.repo_name,
                    Path(entry.path),
                )
                status.update_status("")
                if (
                    self._selected_repo
                    and self._selected_repo.name == entry.repo_name
                ):
                    entries = await self._service.list_worktrees(
                        repo_name=entry.repo_name
                    )
                    worktree_panel = self.query_one(WorktreePanel)
                    worktree_panel.set_worktrees(entries)
                    worktree_panel.select_by_id(entry.id)
                await self._open_worktree_in_terminal(entry)
            except Exception as e:
                status.update_status(f"Error: {e}")

    @work
    async def action_delete_worktree(self) -> None:
        """Delete the selected worktree, or the full mark set when non-empty.

        Guarded by a simple in-progress flag so a second ctrl+d press is
        dropped rather than launching a concurrent worker. A cancelling
        semantic (exclusive=True) would leave the open modal orphaned when
        the first worker is torn down mid-dialog, so we drop instead.
        """
        if self._delete_in_progress:
            return
        self._delete_in_progress = True
        try:
            await self._do_delete_worktree()
        finally:
            self._delete_in_progress = False

    async def _do_delete_worktree(self) -> None:
        if self._selection_cache.count > 0:
            await self._run_bulk_delete()
            return

        worktree_panel = self.query_one(WorktreePanel)
        entry = worktree_panel.get_selected()
        if entry is None:
            return

        dialog = DeleteDialog(entry)
        result = await self.push_screen_wait(dialog)
        if result is None:
            return

        status = self.query_one(GWTStatusBar)
        delete_branch = result.get("delete_branch", False)

        status.update_status(f"Deleting {entry.branch}...")
        try:
            await self._service.delete_worktree(
                entry.id, delete_branch=delete_branch
            )
        except UncommittedChangesError as e:
            force = await self.push_screen_wait(ForceDeleteDialog(str(e)))
            if not force:
                status.update_status("")
                return
            status.update_status(f"Force-deleting {entry.branch}...")
            try:
                await self._service.delete_worktree(
                    entry.id, delete_branch=delete_branch, force=True
                )
            except Exception as e2:
                status.update_status(f"Error: {e2}")
                return
        except Exception as e:
            status.update_status(f"Error: {e}")
            return

        await self._refresh_current_repo_worktrees()
        status.update_status("")

    async def _run_bulk_delete(self) -> None:
        """Run the bulk-delete flow when the selection cache is non-empty."""
        status = self.query_one(GWTStatusBar)
        entries = self._selection_cache.resolved_entries()
        # Snapshot the IDs we're about to process so that concurrent
        # space-toggles for NEW worktrees during the run don't get wiped
        # by our end-of-run clear_succeeded call.
        snapshot_ids = {e.id for e in entries}

        result = await self.push_screen_wait(BulkDeleteDialog(entries))
        if result is None:
            return

        working: list = result["entries"]
        delete_branch: bool = result["delete_branch"]

        def _progress(i: int, total: int, entry) -> None:
            status.update_status(f"Deleting {i} of {total}: {entry.branch}")

        first = await self._service.delete_worktrees_bulk(
            working,
            delete_branch=delete_branch,
            force=False,
            on_progress=_progress,
        )

        force_result = BulkDeleteResult(succeeded=[], dirty=[], failed=[])
        dirty_skipped = 0
        if first.dirty:
            force = await self.push_screen_wait(BulkForceDeleteDialog(first.dirty))
            if force:
                def _force_progress(i: int, total: int, entry) -> None:
                    status.update_status(
                        f"Force-deleting {i} of {total}: {entry.branch}"
                    )

                force_result = await self._service.delete_worktrees_bulk(
                    first.dirty,
                    delete_branch=delete_branch,
                    force=True,
                    on_progress=_force_progress,
                )
            else:
                dirty_skipped = len(first.dirty)

        # Only clear IDs that were in our original snapshot, so any marks
        # added for new worktrees during the run survive.
        to_clear = [
            wid
            for wid in (*first.succeeded, *force_result.succeeded)
            if wid in snapshot_ids
        ]
        self._selection_cache.clear_succeeded(to_clear)

        await self._refresh_current_repo_worktrees()

        succeeded = len(first.succeeded) + len(force_result.succeeded)
        failed = len(first.failed) + len(force_result.failed)
        if failed == 0 and dirty_skipped == 0:
            status.update_status("")
        else:
            status.update_status(
                f"Deleted {succeeded}, failed {failed}, dirty-skipped {dirty_skipped}"
            )

    async def _refresh_current_repo_worktrees(self) -> None:
        if not self._selected_repo:
            return
        try:
            worktrees = await git.list_worktrees(self._selected_repo.path)
            self._metadata.reconcile(worktrees, repo_name=self._selected_repo.name)
        except Exception:
            pass
        entries = await self._service.list_worktrees(
            repo_name=self._selected_repo.name
        )
        # Drop cache entries for worktrees that no longer exist in this repo
        # (e.g., deleted out-of-band), so the status bar count stays accurate.
        self._selection_cache.prune_for_repo(
            self._selected_repo.name, [e.id for e in entries]
        )
        worktree_panel = self.query_one(WorktreePanel)
        worktree_panel.set_worktrees(entries)

    @work
    async def action_open_worktree(self) -> None:
        """Open the selected worktree using the configured terminal."""
        worktree_panel = self.query_one(WorktreePanel)
        entry = worktree_panel.get_selected()
        if entry is None:
            return
        await self._open_worktree_in_terminal(entry)

    async def _open_worktree_in_terminal(self, entry: WorktreeEntry) -> None:
        """Open a worktree entry using the configured terminal/multiplexer."""
        try:
            await self._service.open_worktree(entry.id)
            status_msg = await asyncio.to_thread(
                self._terminal_opener.open, entry.branch, entry.path
            )
            self.query_one(GWTStatusBar).update_status(status_msg)
        except Exception as e:
            self.query_one(GWTStatusBar).update_status(f"Error: {e}")

    @work
    async def action_edit_worktree(self) -> None:
        """Open the selected worktree in the configured editor."""
        worktree_panel = self.query_one(WorktreePanel)
        entry = worktree_panel.get_selected()
        if entry is None:
            return

        editor = self._config.editor

        if editor == "terminal":
            # Use editor_terminal if set, otherwise fall back to default terminal
            term = self._config.editor_terminal or self._config.terminal
            opener = TerminalOpener(terminal=term, ai_assistant="none")
            await asyncio.to_thread(opener.open, entry.branch, entry.path)
            self.query_one(GWTStatusBar).update_status(f"Opened terminal: {entry.branch}")
            return

        cmd = editor
        try:
            subprocess.Popen(
                [cmd, entry.path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.query_one(GWTStatusBar).update_status(f"Opened in {editor}: {entry.branch}")
        except FileNotFoundError:
            self.query_one(GWTStatusBar).update_status(f"Editor not found: {cmd}")

    @work
    async def action_open_issue_url(self) -> None:
        """Open the issue URL for the selected worktree in the browser."""
        worktree_panel = self.query_one(WorktreePanel)
        entry = worktree_panel.get_selected()
        if entry is None:
            return
        url = entry.issue_url
        if not url:
            self.query_one(GWTStatusBar).update_status("No issue URL for this worktree")
            return
        await asyncio.to_thread(webbrowser.open, url)
        self.query_one(GWTStatusBar).update_status(f"Opened: {url}")

    async def action_refresh(self) -> None:
        """Refresh repos, reconcile metadata, and restore selection."""
        status = self.query_one(GWTStatusBar)
        status.update_status("Refreshing...")

        previous_repo = self._selected_repo

        self._repos = await self._discovery.discover_repos()
        for repo in self._repos:
            try:
                worktrees = await git.list_worktrees(repo.path)
                self._metadata.reconcile(worktrees, repo_name=repo.name)
            except Exception:
                pass

        repo_panel = self.query_one(RepoPanel)
        repo_panel.set_repos(self._repos)

        if previous_repo:
            repo_panel.select_by_name(previous_repo.name)

        status.update_status("")

    @work
    async def action_yank(self) -> None:
        """Copy the selected worktree path to the clipboard."""
        worktree_panel = self.query_one(WorktreePanel)
        entry = worktree_panel.get_selected()
        if entry:
            try:
                self._copy_to_clipboard(entry.path)
                self.query_one(GWTStatusBar).update_status(
                    f"Copied: {entry.path}"
                )
            except Exception:
                self.query_one(GWTStatusBar).update_status(
                    f"Path: {entry.path}"
                )

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        """Copy text to clipboard using OS-appropriate command."""
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
        elif system == "Windows":
            subprocess.run(["clip"], input=text.encode(), check=True)
        else:
            # Linux: try wl-copy (Wayland), then xclip, then xsel
            if shutil.which("wl-copy"):
                subprocess.run(["wl-copy"], input=text.encode(), check=True)
            elif shutil.which("xclip"):
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode(), check=True,
                )
            elif shutil.which("xsel"):
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode(), check=True,
                )
            else:
                raise RuntimeError("No clipboard tool found (wl-copy, xclip, or xsel)")

    def action_focus_next_panel(self) -> None:
        """Cycle focus to the next focusable panel."""
        self.action_focus_next()

    async def action_move_worktree(self) -> None:
        """Placeholder for move — not yet available in TUI."""
        self.notify("Move not yet available in TUI. Use CLI: gwt move", timeout=3)

    async def action_switch_worktree(self) -> None:
        """Placeholder for switch — not yet available in TUI."""
        self.notify("Switch not yet available in TUI. Use CLI: gwt switch", timeout=3)

    async def action_help(self) -> None:
        """Show keyboard shortcut help."""
        self.notify(
            "^N=New ^D=Delete ^O=Open ^E=Edit ^R=Refresh ^Y=Copy ^U=URL ^Q=Quit Tab=Panel",
            title="Keyboard Shortcuts",
            timeout=5,
        )


def run_tui() -> str | None:
    """Run the TUI application and return the result.

    Returns a ``__GWT_CD__:<path>`` string when the user opens a worktree
    that requires a shell ``cd``, otherwise returns ``None``.
    """
    app = GWTApp()
    result = app.run()
    return result
