"""Worktree panel widget for the GWT Worktree Manager TUI."""

from textual.widgets import Static, DataTable, Label
from textual.message import Message

from gwt_worktree_manager.store.metadata import WorktreeEntry


class WorktreePanel(Static):
    """Main panel showing worktrees for the selected repo."""

    class WorktreeSelected(Message):
        """Message posted when a worktree entry is selected."""

        def __init__(self, entry: WorktreeEntry) -> None:
            self.entry = entry
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._entries: list[WorktreeEntry] = []
        self._table: DataTable | None = None
        self._empty_label: Label | None = None

    def compose(self):
        """Compose the worktree panel."""
        yield Label("WORKTREES", classes="panel-title")
        self._empty_label = Label("No worktrees. Press [c] to create one.")
        yield self._empty_label
        self._table = DataTable()
        self._table.add_columns("Branch", "Issue", "Type")
        self._table.display = False
        yield self._table

    def set_worktrees(self, entries: list[WorktreeEntry]) -> None:
        """Set the list of worktree entries to display."""
        self._entries = sorted(
            entries, key=lambda e: e.last_accessed or "", reverse=True
        )
        if self._table is None or self._empty_label is None:
            return
        self._table.clear()

        if not self._entries:
            self._empty_label.display = True
            self._table.display = False
            return

        self._empty_label.display = False
        self._table.display = True

        for entry in self._entries:
            self._table.add_row(
                entry.branch,
                entry.issue_id or "-",
                entry.work_type or "-",
                key=entry.id,
            )

    def get_selected(self) -> WorktreeEntry | None:
        """Return the currently highlighted worktree entry."""
        if not self._entries or self._table is None:
            return None
        cursor_row = self._table.cursor_row
        if 0 <= cursor_row < len(self._entries):
            return self._entries[cursor_row]
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the data table."""
        entry = self.get_selected()
        if entry:
            self.post_message(self.WorktreeSelected(entry))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlight changes in the data table."""
        entry = self.get_selected()
        if entry:
            self.post_message(self.WorktreeSelected(entry))
