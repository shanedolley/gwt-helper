"""Detail panel widget for the GWT Worktree Manager TUI."""

from textual.widgets import Static, Label

from gwt_worktree_manager.store.metadata import WorktreeEntry


class DetailPanel(Static):
    """Bottom panel showing details for the selected worktree."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._content: Label | None = None

    def compose(self):
        """Compose the detail panel."""
        yield Label("DETAILS", classes="panel-title")
        self._content = Label("Select a worktree to view details.")
        yield self._content

    def set_worktree(self, entry: WorktreeEntry | None) -> None:
        """Display details for the given worktree entry."""
        if self._content is None:
            return
        if entry is None:
            self._content.update("Select a worktree to view details.")
            return

        tracker_label = {"ado": "Azure DevOps", "linear": "Linear"}.get(
            entry.issue_tracker, entry.issue_tracker or "none"
        )
        lines = [
            f"Branch: {entry.branch}",
            f"Source: {entry.source_branch or 'unknown'}",
            f"Path: {entry.path}",
            f"Issue: {entry.issue_id or 'none'}",
            f"Tracker: {tracker_label}",
            f"URL: {entry.issue_url or 'none'}",
            f"Type: {entry.work_type or 'none'}",
            f"Created: {entry.created_at[:10] if entry.created_at else 'unknown'}",
            f"Accessed: {entry.last_accessed[:10] if entry.last_accessed else 'unknown'}",
            f"Tags: {', '.join(entry.tags) if entry.tags else 'none'}",
        ]
        self._content.update("\n".join(lines))
