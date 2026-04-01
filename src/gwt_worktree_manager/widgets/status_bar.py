"""Status bar widget for the GWT Worktree Manager TUI."""

from textual.widgets import Static


class GWTStatusBar(Static):
    """Bottom status bar with state info."""

    def __init__(self, **kwargs):
        super().__init__("Starting...", **kwargs)

    def update_status(self, message: str) -> None:
        """Update the status bar message."""
        self.update(message)
