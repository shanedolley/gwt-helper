"""Repository panel widget for the GWT Worktree Manager TUI."""

from collections import defaultdict

from textual.binding import Binding
from textual.widgets import Static, Tree, Label, Input
from textual.message import Message


class RepoTree(Tree):
    """Tree with left/right arrow keys for collapse/expand."""

    BINDINGS = [
        *Tree.BINDINGS,
        Binding("left", "collapse_node", "Collapse", show=False),
        Binding("right", "expand_node", "Expand", show=False),
    ]

    def action_collapse_node(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and node.is_expanded:
            node.collapse()
        elif node.parent and node.parent != self.root:
            self.select_node(node.parent)

    def action_expand_node(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and not node.is_expanded:
            node.expand()


class RepoPanel(Static):
    """Left panel showing discovered repositories as a tree grouped by org."""

    class RepoSelected(Message):
        """Message posted when a repo is highlighted."""

        def __init__(self, repo) -> None:
            self.repo = repo
            super().__init__()

    class RepoConfirmed(Message):
        """Message posted when Enter is pressed on a repo."""

        def __init__(self, repo) -> None:
            self.repo = repo
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._repos = []
        self._tree: RepoTree | None = None
        self._filter_input: Input | None = None
        self._filter_text: str = ""
        self._filtering: bool = False

    def compose(self):
        """Compose the repo panel."""
        yield Label("REPOSITORIES", classes="panel-title")
        self._filter_input = Input(
            placeholder="Type to filter...",
            id="repo-filter",
        )
        self._filter_input.display = False
        yield self._filter_input
        self._tree = RepoTree("repos", id="repo-tree")
        self._tree.show_root = False
        self._tree.guide_depth = 2
        yield self._tree

    def on_key(self, event) -> None:
        """Handle key events for filtering and tree navigation."""
        # Forward up/down arrows from filter input to the tree
        if (
            self._filtering
            and self._filter_input is not None
            and self._filter_input.has_focus
            and self._tree is not None
            and event.key in ("up", "down")
        ):
            if event.key == "up":
                self._tree.action_cursor_up()
            else:
                self._tree.action_cursor_down()
            event.prevent_default()
            return

        # Start filtering when typing on the tree
        if (
            self._tree is not None
            and self._tree.has_focus
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
        """Filter repos when the filter input changes."""
        if event.input.id == "repo-filter":
            self._filter_text = event.value
            self._rebuild_tree()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Confirm the highlighted repo when Enter is pressed in filter."""
        if event.input.id == "repo-filter" and self._tree is not None:
            node = self._tree.cursor_node
            if node is not None and node.data is not None:
                self.post_message(self.RepoConfirmed(node.data))

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
            self._rebuild_tree()
        else:
            # Second escape (or first if already empty): close filter entirely
            self._filter_input.value = ""
            self._filter_text = ""
            self._filter_input.display = False
            self._filtering = False
            self._rebuild_tree()
            if self._tree is not None:
                self._tree.focus()

    def set_repos(self, repos: list) -> None:
        """Set the list of repos to display, grouped by org."""
        self._repos = repos
        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        """Rebuild the tree with current repos and filter."""
        if self._tree is None:
            return
        self._tree.clear()

        filtered = self._repos
        if self._filter_text:
            query = self._filter_text.lower()
            filtered = [r for r in self._repos if query in r.name.lower()]

        if not filtered:
            self._tree.root.add_leaf("No matches." if self._filter_text else "No repos found.")
            return

        grouped = defaultdict(list)
        for repo in filtered:
            org = repo.org or "(root)"
            grouped[org].append(repo)

        for org in sorted(grouped.keys()):
            org_node = self._tree.root.add(org, expand=True)
            for repo in sorted(grouped[org], key=lambda r: r.name.lower()):
                org_node.add_leaf(repo.name, data=repo)

    def select_by_name(self, name: str) -> None:
        """Move cursor to the tree node with the given repo name."""
        if self._tree is None:
            return
        for node in self._tree.root.children:
            for child in node.children:
                if child.data is not None and child.data.name == name:
                    self._tree.select_node(child)
                    node.expand()
                    return

    def focus_tree(self) -> None:
        """Focus the repo tree."""
        if self._tree is not None:
            self._tree.focus()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Handle tree node highlight (cursor movement)."""
        if event.node.data is not None:
            self.post_message(self.RepoSelected(event.node.data))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle Enter press on a tree node."""
        if event.node.data is not None:
            self.post_message(self.RepoConfirmed(event.node.data))
