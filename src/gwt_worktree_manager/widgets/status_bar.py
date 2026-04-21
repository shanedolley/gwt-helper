"""Status bar widget for the GWT Worktree Manager TUI."""

from textual.reactive import reactive
from textual.widgets import Static


class GWTStatusBar(Static):
    """Bottom status bar with state info and marked-count suffix."""

    mark_count: reactive[int] = reactive(0)

    def __init__(self, **kwargs):
        super().__init__("Starting...", **kwargs)
        self._base_message: str = "Starting..."

    def update_status(self, message: str) -> None:
        """Update the status bar message."""
        self._base_message = message
        self._refresh()

    def watch_mark_count(self, _old: int, _new: int) -> None:
        self._refresh()

    def _refresh(self) -> None:
        suffix = f"{self.mark_count} marked" if self.mark_count > 0 else ""
        if self._base_message and suffix:
            self.update(f"{self._base_message} | {suffix}")
        elif suffix:
            self.update(suffix)
        else:
            self.update(self._base_message)
