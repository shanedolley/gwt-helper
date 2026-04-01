"""Textual TUI application for GWT Worktree Manager."""

import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header

from gwt_worktree_manager.config.manager import load_config
from gwt_worktree_manager.git import operations as git
from gwt_worktree_manager.services.discovery import RepoDiscovery
from gwt_worktree_manager.services.hooks import HookRunner
from gwt_worktree_manager.services.worktree import WorktreeService
from gwt_worktree_manager.store.metadata import MetadataStore
from gwt_worktree_manager.widgets.detail_panel import DetailPanel
from gwt_worktree_manager.widgets.dialogs import CreateDialog, DeleteDialog
from gwt_worktree_manager.widgets.repo_panel import RepoPanel
from gwt_worktree_manager.widgets.status_bar import GWTStatusBar
from gwt_worktree_manager.widgets.worktree_panel import WorktreePanel


class GWTApp(App):
    """GWT Worktree Manager TUI Application."""

    TITLE = "GWT Worktree Manager"

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
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        Binding("c", "create", "Create"),
        Binding("d", "delete_worktree", "Delete"),
        Binding("o", "open_worktree", "Open"),
        Binding("r", "refresh", "Refresh"),
        Binding("y", "yank", "Copy Path"),
        Binding("tab", "focus_next_panel", "Next Panel"),
        Binding("slash", "search", "Search"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config = load_config()
        self._metadata = MetadataStore()
        self._discovery = RepoDiscovery(self._config)
        self._service = WorktreeService(self._config, self._metadata, self._discovery)
        self._hook_runner = HookRunner(self._config)
        self._repos: list = []
        self._selected_repo = None

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()
        with Horizontal(id="main-area"):
            with Vertical(id="left-panel"):
                yield RepoPanel(id="repo-panel")
            with Vertical(id="right-panel"):
                yield WorktreePanel(id="worktree-panel")
                yield DetailPanel(id="detail-panel")
        yield GWTStatusBar(id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Load data after the app mounts."""
        status = self.query_one(GWTStatusBar)
        status.update_status("Scanning repos...")

        self._repos = await self._discovery.discover_repos()
        repo_panel = self.query_one(RepoPanel)
        repo_panel.set_repos(self._repos)

        for repo in self._repos:
            try:
                worktrees = await git.list_worktrees(repo.path)
                self._metadata.reconcile(worktrees)
            except Exception:
                pass

        status.update_status(f"Ready | {len(self._repos)} repos")

    async def on_repo_panel_repo_selected(self, event: RepoPanel.RepoSelected) -> None:
        """Handle repo selection from the repo panel."""
        self._selected_repo = event.repo
        worktree_panel = self.query_one(WorktreePanel)
        entries = await self._service.list_worktrees(repo_name=event.repo.name)
        worktree_panel.set_worktrees(entries)

        status = self.query_one(GWTStatusBar)
        status.update_status(
            f"Ready | {len(self._repos)} repos | {event.repo.name}"
        )

    async def on_worktree_panel_worktree_selected(
        self, event: WorktreePanel.WorktreeSelected
    ) -> None:
        """Handle worktree selection from the worktree panel."""
        detail_panel = self.query_one(DetailPanel)
        detail_panel.set_worktree(event.entry)

    async def action_create(self) -> None:
        """Open the create worktree dialog."""
        dialog = CreateDialog(self._repos, self._config)
        result = await self.push_screen_wait(dialog)
        if result:
            status = self.query_one(GWTStatusBar)
            status.update_status("Creating worktree...")
            try:
                entry = await self._service.create_worktree(**result)
                status.update_status("Running hooks...")
                await self._hook_runner.run_post_create_hooks(
                    entry.repo_name,
                    Path(entry.path),
                )
                status.update_status(f"Created: {entry.branch}")
                if (
                    self._selected_repo
                    and self._selected_repo.name == entry.repo_name
                ):
                    entries = await self._service.list_worktrees(
                        repo_name=entry.repo_name
                    )
                    self.query_one(WorktreePanel).set_worktrees(entries)
            except Exception as e:
                status.update_status(f"Error: {e}")

    async def action_delete_worktree(self) -> None:
        """Delete the selected worktree after confirmation."""
        worktree_panel = self.query_one(WorktreePanel)
        entry = worktree_panel.get_selected()
        if entry is None:
            return

        dialog = DeleteDialog(entry)
        result = await self.push_screen_wait(dialog)
        if result is not None:
            status = self.query_one(GWTStatusBar)
            try:
                await self._service.delete_worktree(
                    entry.id, delete_branch=result.get("delete_branch", False)
                )
                status.update_status(f"Deleted: {entry.branch}")
                if self._selected_repo:
                    entries = await self._service.list_worktrees(
                        repo_name=self._selected_repo.name
                    )
                    worktree_panel.set_worktrees(entries)
            except Exception as e:
                status.update_status(f"Error: {e}")

    async def action_open_worktree(self) -> None:
        """Open the selected worktree using the configured action."""
        worktree_panel = self.query_one(WorktreePanel)
        entry = worktree_panel.get_selected()
        if entry is None:
            return
        try:
            result = await self._service.open_worktree(entry.id)
            if result.action == "cd":
                self.exit(result=f"__GWT_CD__:{result.cd_path}")
            else:
                subprocess.run(
                    result.command_executed,
                    shell=True,
                    cwd=entry.path,
                )
        except Exception as e:
            self.query_one(GWTStatusBar).update_status(f"Error: {e}")

    async def action_refresh(self) -> None:
        """Refresh the repo and worktree lists."""
        status = self.query_one(GWTStatusBar)
        status.update_status("Refreshing...")
        self._repos = await self._discovery.discover_repos()
        self.query_one(RepoPanel).set_repos(self._repos)
        status.update_status(f"Ready | {len(self._repos)} repos")

    async def action_yank(self) -> None:
        """Copy the selected worktree path to the clipboard."""
        worktree_panel = self.query_one(WorktreePanel)
        entry = worktree_panel.get_selected()
        if entry:
            try:
                subprocess.run(
                    ["pbcopy"], input=entry.path.encode(), check=True
                )
                self.query_one(GWTStatusBar).update_status(
                    f"Copied: {entry.path}"
                )
            except Exception:
                self.query_one(GWTStatusBar).update_status(
                    f"Path: {entry.path}"
                )

    def action_focus_next_panel(self) -> None:
        """Cycle focus to the next focusable panel."""
        self.action_focus_next()

    async def action_search(self) -> None:
        """Search placeholder — currently a no-op."""

    async def action_help(self) -> None:
        """Show keyboard shortcut help."""
        self.notify(
            "Keys: c=Create d=Delete o=Open r=Refresh y=Copy /=Search q=Quit Tab=Next Panel",
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
