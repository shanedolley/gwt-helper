"""Repository panel widget for the GWT Worktree Manager TUI."""

from textual.widgets import Static, ListView, ListItem, Label
from textual.message import Message


class RepoPanel(Static):
    """Left panel showing discovered repositories."""

    class RepoSelected(Message):
        """Message posted when a repo is selected."""

        def __init__(self, repo) -> None:
            self.repo = repo
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._repos = []
        self._list_view: ListView | None = None

    def compose(self):
        """Compose the repo panel."""
        yield Label("REPOSITORIES", classes="panel-title")
        self._list_view = ListView()
        yield self._list_view

    def set_repos(self, repos: list) -> None:
        """Set the list of repos to display."""
        self._repos = repos
        if self._list_view is None:
            return
        self._list_view.clear()
        if not repos:
            self._list_view.append(ListItem(Label("No repos found.")))
            return
        for repo in repos:
            item = ListItem(Label(repo.name))
            item._repo = repo
            self._list_view.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle repo selection from the list."""
        if hasattr(event.item, "_repo"):
            self.post_message(self.RepoSelected(event.item._repo))
