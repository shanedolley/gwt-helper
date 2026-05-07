"""Worktree panel widget for the GWT Worktree Manager TUI."""

from rich.text import Text
from textual.widgets import Static, DataTable, Label, Input
from textual.message import Message

from gwt_worktree_manager.state.selection_cache import SelectionCache
from gwt_worktree_manager.store.metadata import WorktreeEntry


MARKER_ON = "●"
MARKER_OFF = " "


MARKED_ROW_STYLE = "bold reverse"


class WorktreePanel(Static):
    """Main panel showing worktrees for the selected repo."""

    class WorktreeSelected(Message):
        """Message posted when a worktree entry is selected."""

        def __init__(self, entry: WorktreeEntry) -> None:
            self.entry = entry
            super().__init__()

    def __init__(self, selection_cache: SelectionCache | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._entries: list[WorktreeEntry] = []
        self._table: DataTable | None = None
        self._empty_label: Label | None = None
        self._filter_input: Input | None = None
        self._filter_text: str = ""
        self._filtering: bool = False
        self._filtered_entries: list[WorktreeEntry] = []
        self._cache = selection_cache or SelectionCache()

    def compose(self):
        """Compose the worktree panel."""
        yield Label("WORKTREES", classes="panel-title")
        self._filter_input = Input(
            placeholder="Type to filter...",
            id="worktree-filter",
        )
        self._filter_input.display = False
        yield self._filter_input
        self._empty_label = Label("No worktrees. Press [c] to create one.")
        yield self._empty_label
        self._table = DataTable(cursor_type="row")
        self._table.add_columns(" ", "Branch", "Issue", "Type")
        self._table.display = False
        yield self._table

    def on_key(self, event) -> None:
        """Handle key events for filtering and table navigation."""
        # Forward up/down arrows from filter input to the table
        if (
            self._filtering
            and self._filter_input is not None
            and self._filter_input.has_focus
            and self._table is not None
            and event.key in ("up", "down")
        ):
            if event.key == "up":
                self._table.action_cursor_up()
            else:
                self._table.action_cursor_down()
            event.prevent_default()
            return

        # Toggle mark with space when the table has focus
        if (
            event.key == "space"
            and self._table is not None
            and self._table.has_focus
            and not self._filtering
        ):
            entry = self.get_selected()
            if entry is None:
                event.prevent_default()
                return
            self._cache.toggle(entry)
            event.prevent_default()
            cursor_row = self._table.cursor_row
            self._rebuild_table()
            entries = self._filtered_entries or self._entries
            if cursor_row < len(entries) - 1:
                self._table.move_cursor(row=cursor_row + 1)
            else:
                self._table.move_cursor(row=cursor_row)
            return

        # Start filtering when typing on the table
        if (
            self._table is not None
            and self._table.has_focus
            and self._filter_input is not None
            and not self._filtering
            and len(event.character or "") == 1
            and (event.character.isalnum() or event.character in "-_.")
        ):
            self._filtering = True
            self._filter_input.display = True
            self._filter_input.focus()
            char = event.character
            def _set_value():
                self._filter_input.value = char
                self._filter_input.cursor_position = len(char)
            self.call_after_refresh(_set_value)
            event.prevent_default()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter worktrees when the filter input changes."""
        if event.input.id == "worktree-filter":
            self._filter_text = event.value
            self._rebuild_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Return focus to the table when Enter is pressed in filter."""
        if event.input.id == "worktree-filter" and self._table is not None:
            self._table.focus()

    def key_escape(self) -> None:
        """First Escape clears filter text. Second Escape closes filter."""
        if self._filter_input is None:
            return
        if not self._filtering:
            return
        if self._filter_input.has_focus and self._filter_text:
            # First escape: clear the filter text but keep input visible
            self._filter_input.value = ""
            self._filter_text = ""
            self._rebuild_table()
        else:
            # Second escape (or first if already empty): close filter entirely
            self._filter_input.value = ""
            self._filter_text = ""
            self._filter_input.display = False
            self._filtering = False
            self._rebuild_table()
            if self._table is not None:
                self._table.focus()

    def set_worktrees(self, entries: list[WorktreeEntry]) -> None:
        """Set the list of worktree entries to display."""
        by_recency = sorted(entries, key=lambda e: e.last_accessed or "", reverse=True)
        self._entries = sorted(
            by_recency,
            key=lambda e: (e.work_type or "", e.issue_id or "", e.branch or ""),
        )
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        """Rebuild the table with current entries and filter."""
        if self._table is None or self._empty_label is None:
            return
        self._table.clear()

        filtered = self._entries
        if self._filter_text:
            query = self._filter_text.lower()
            filtered = [
                e for e in self._entries
                if query in (e.branch or "").lower()
                or query in (e.issue_id or "").lower()
                or query in (e.work_type or "").lower()
            ]

        self._filtered_entries = filtered

        if not filtered:
            self._empty_label.display = True
            self._table.display = False
            self._empty_label.update(
                "No matches." if self._filter_text else "No worktrees. Press [c] to create one."
            )
            return

        self._empty_label.display = False
        self._table.display = True

        for entry in filtered:
            marked = self._cache.contains(entry.id)
            style = MARKED_ROW_STYLE if marked else ""
            marker = MARKER_ON if marked else MARKER_OFF
            self._table.add_row(
                Text(marker, style=style),
                Text(entry.branch, style=style),
                Text(entry.issue_id or "-", style=style),
                Text(entry.work_type or "-", style=style),
                key=entry.id,
            )

    def get_selected(self) -> WorktreeEntry | None:
        """Return the currently highlighted worktree entry."""
        entries = self._filtered_entries or self._entries
        if not entries or self._table is None:
            return None
        cursor_row = self._table.cursor_row
        if 0 <= cursor_row < len(entries):
            return entries[cursor_row]
        return None

    def select_by_id(self, entry_id: str) -> None:
        """Move the cursor to the row matching the given entry ID."""
        if self._table is None:
            return
        entries = self._filtered_entries or self._entries
        for i, entry in enumerate(entries):
            if entry.id == entry_id:
                self._table.move_cursor(row=i)
                return

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
