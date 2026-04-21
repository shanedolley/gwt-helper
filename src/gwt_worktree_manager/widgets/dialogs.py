"""Modal dialog widgets for the GWT Worktree Manager TUI."""

from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Select,
)
from textual.containers import Vertical, Horizontal, VerticalScroll

import re

from gwt_worktree_manager.git import operations as git
from gwt_worktree_manager.services.worktree import VALID_WORK_TYPES, to_kebab_case
from gwt_worktree_manager.store.metadata import WorktreeEntry

DIALOG_BUTTON_CSS = """
    .dialog-buttons {
        height: auto;
        margin-top: 1;
        align: right middle;
    }
    .dialog-buttons Button {
        min-width: 12;
        height: 1;
        border: none;
        margin: 0 1;
        color: white;
    }
"""


class CreateDialog(ModalScreen):
    """Modal dialog for creating a new worktree."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = DIALOG_BUTTON_CSS + """
    CreateDialog {
        align: center middle;
    }

    #create-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #pr-row {
        height: auto;
    }

    #pr-row Input {
        width: 1fr;
    }

    #pr-row Button {
        min-width: 10;
        height: 1;
        border: none;
        margin: 0 0 0 1;
    }

    #pr-branch-label {
        color: $success;
    }
    """

    def __init__(self, repos: list, config, default_repo: str | None = None) -> None:
        super().__init__()
        self._repos = repos
        self._config = config
        self._default_repo = default_repo
        self._repo_paths = {r.name: r.path for r in repos}
        self._resolved_pr_branch: str = ""

    def compose(self):
        """Compose the create dialog."""
        default_tracker = getattr(self._config, "default_issue_tracker", "ado")
        with VerticalScroll(id="create-dialog"):
            yield Label("Create Worktree", classes="dialog-title")
            yield Label("Repository:")
            yield Select(
                [(r.name, r.name) for r in self._repos],
                id="repo-select",
                allow_blank=True,
            )
            yield Label("Work Type:")
            yield Select(
                [(t, t) for t in sorted(VALID_WORK_TYPES)],
                id="type-select",
                prompt="Select type",
                allow_blank=True,
            )
            yield Label("PR Number:", id="pr-label")
            with Horizontal(id="pr-row"):
                yield Input(placeholder="e.g., 1234 or full PR URL", id="pr-input")
                yield Button("Search", variant="primary", id="btn-search")
            yield Label("", id="pr-branch-label")
            yield Label("Issue Tracker:", id="tracker-label")
            yield Select(
                [("Azure DevOps", "ado"), ("Linear", "linear")],
                value=default_tracker,
                id="tracker-select",
                allow_blank=False,
            )
            yield Label("Issue ID:", id="issue-label")
            yield Input(placeholder="e.g., 1234", id="issue-input")
            yield Label("Description:", id="desc-label")
            yield Input(placeholder="Short description", id="desc-input")
            yield Label("Source Branch:", id="source-label")
            yield Select(
                [],
                id="source-select",
                prompt="Select repo first",
                allow_blank=True,
            )
            yield Label("", id="preview-label")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("Create", variant="primary", id="btn-create")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update the branch preview when input changes."""
        self._update_preview()

    async def on_mount(self) -> None:
        """Load branches if a default repo is set. Hide PR field initially."""
        self._set_pr_review_mode(False)
        if self._default_repo:
            self.query_one("#repo-select", Select).value = self._default_repo
            await self._load_branches(self._default_repo)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Update the branch preview and reload branches when repo changes."""
        self._update_preview()
        if event.select.id == "repo-select" and event.value is not Select.BLANK:
            self.run_worker(self._load_branches(event.value))
        if event.select.id == "type-select":
            is_pr = event.value == "pr-review"
            self._set_pr_review_mode(is_pr)

    def _set_pr_review_mode(self, enabled: bool) -> None:
        """Toggle between PR review fields and normal fields."""
        pr_widgets = ["#pr-label", "#pr-row", "#pr-branch-label"]
        normal_widgets = [
            "#tracker-label", "#tracker-select",
            "#issue-label", "#issue-input",
            "#desc-label", "#desc-input",
            "#source-label", "#source-select",
        ]
        for sel in pr_widgets:
            self.query_one(sel).display = enabled
        for sel in normal_widgets:
            self.query_one(sel).display = not enabled

    async def _load_branches(self, repo_name: str) -> None:
        """Fetch remote branches for a repo and populate the source branch dropdown."""
        source_select = self.query_one("#source-select", Select)
        repo_path = self._repo_paths.get(repo_name)
        if repo_path is None:
            return
        try:
            branches = await git.list_branches(repo_path, include_remote=True)
            # Strip remote prefix (e.g., "origin/main" -> "main"), deduplicate
            clean = []
            seen = set()
            for b in branches:
                name = b.split("/", 1)[1] if "/" in b and b.startswith("origin/") else b
                if name not in seen and name != "HEAD":
                    seen.add(name)
                    clean.append(name)
            clean.sort()
            options = [(b, b) for b in clean]
            source_select.set_options(options)
            # Pre-select the default source branch if it exists
            default = self._config.get_repo_config(repo_name).source_branch or self._config.default_source_branch
            if default in seen:
                source_select.value = default
        except Exception:
            source_select.set_options([])

    async def _search_pr(self) -> None:
        """Look up the PR branch name from GitHub."""
        import asyncio

        pr_input = self.query_one("#pr-input", Input).value
        pr_number = self._extract_pr_number(pr_input)
        if not pr_number:
            self.notify("Enter a valid PR number or URL", severity="error")
            return

        repo_select = self.query_one("#repo-select", Select)
        repo = repo_select.value
        if repo is Select.NULL or not repo:
            self.notify("Select a repository first", severity="error")
            return

        repo_path = self._repo_paths.get(repo)
        if repo_path is None:
            self.notify("Repository path not found", severity="error")
            return

        branch_label = self.query_one("#pr-branch-label", Label)
        branch_label.update("Searching...")

        try:
            proc = await asyncio.create_subprocess_exec(
                "gh", "pr", "view", pr_number,
                "--json", "headRefName",
                "-q", ".headRefName",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode != 0:
                branch_label.update(f"Error: {stderr.decode().strip()}")
                self._resolved_pr_branch = ""
                return
            branch = stdout.decode().strip()
            if not branch:
                branch_label.update("Error: PR has no branch")
                self._resolved_pr_branch = ""
                return
            self._resolved_pr_branch = branch
            branch_label.update(f"Branch: {branch}")
        except FileNotFoundError:
            branch_label.update("Error: gh CLI not found")
            self._resolved_pr_branch = ""
        except asyncio.TimeoutError:
            branch_label.update("Error: search timed out")
            self._resolved_pr_branch = ""

    def _update_preview(self) -> None:
        """Compute and display a preview of the branch name."""
        try:
            type_select = self.query_one("#type-select", Select)
            work_type = type_select.value
            if work_type == "pr-review":
                pr_num = self._extract_pr_number(
                    self.query_one("#pr-input", Input).value
                )
                if pr_num:
                    self.query_one("#preview-label", Label).update(
                        f"Preview: pr-review/{pr_num}"
                    )
                else:
                    self.query_one("#preview-label", Label).update("")
                return
            issue_id = self.query_one("#issue-input", Input).value
            desc = self.query_one("#desc-input", Input).value
            if work_type is not Select.NULL and work_type and desc:
                kebab = to_kebab_case(desc)
                if issue_id:
                    preview = f"Preview: {work_type}/{issue_id}-{kebab}"
                else:
                    preview = f"Preview: {work_type}/{kebab}"
                self.query_one("#preview-label", Label).update(preview)
            else:
                self.query_one("#preview-label", Label).update("")
        except Exception:
            pass

    @staticmethod
    def _extract_pr_number(value: str) -> str:
        """Extract PR number from a URL or plain number."""
        value = value.strip()
        if not value:
            return ""
        # Match PR URL patterns: .../pull/123 or .../pullrequest/123
        match = re.search(r"/pull(?:request)?/(\d+)", value)
        if match:
            return match.group(1)
        # Plain number
        if value.isdigit():
            return value
        return ""

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)

    def _submit(self) -> None:
        """Submit the create form."""
        repo_select = self.query_one("#repo-select", Select)
        type_select = self.query_one("#type-select", Select)
        repo = repo_select.value
        work_type = type_select.value

        if repo is Select.NULL or not repo:
            self.notify("Please select a repository", severity="error")
            return
        if work_type is Select.NULL or not work_type:
            self.notify("Please select a work type", severity="error")
            return

        # PR review has a different submission path
        if work_type == "pr-review":
            pr_number = self._extract_pr_number(
                self.query_one("#pr-input", Input).value
            )
            if not pr_number:
                self.notify("Please enter a valid PR number or URL", severity="error")
                return
            self.dismiss(
                {
                    "repo_name": repo,
                    "work_type": "pr-review",
                    "pr_number": pr_number,
                }
            )
            return

        # Normal worktree submission
        tracker_select = self.query_one("#tracker-select", Select)
        tracker = tracker_select.value
        source_select = self.query_one("#source-select", Select)
        source_val = source_select.value
        issue_id = self.query_one("#issue-input", Input).value.strip()
        desc = self.query_one("#desc-input", Input).value.strip()
        source = source_val if source_val is not Select.BLANK else None

        if not desc:
            self.notify("Please enter a description", severity="error")
            return

        issue_url = self._config.get_issue_url(repo, tracker, issue_id)

        self.dismiss(
            {
                "repo_name": repo,
                "work_type": work_type,
                "issue_id": issue_id,
                "issue_tracker": tracker,
                "issue_url": issue_url,
                "description": desc,
                "source_branch": source,
            }
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-create":
            self._submit()
        elif event.button.id == "btn-search":
            self.run_worker(self._search_pr())


class DeleteDialog(ModalScreen):
    """Modal dialog for confirming worktree deletion."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = DIALOG_BUTTON_CSS + """
    DeleteDialog {
        align: center middle;
    }

    #delete-dialog {
        width: 60;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }

    #branch-radio RadioButton {
        height: 1;
        padding: 0;
        margin: 0;
    }
    #branch-radio {
        height: auto;
    }
    """

    def __init__(self, entry: WorktreeEntry) -> None:
        super().__init__()
        self._entry = entry

    def compose(self):
        """Compose the delete confirmation dialog."""
        with VerticalScroll(id="delete-dialog"):
            yield Label("Delete Worktree", classes="dialog-title")
            yield Label(f"Branch: {self._entry.branch}")
            yield Label(f"Repo: {self._entry.repo_name}")
            yield Label(f"Path: {self._entry.path}")
            yield Label("")
            yield Label("Are you sure you want to delete this worktree?")
            yield Label("")
            yield Label("Also delete the branch?")
            with RadioSet(id="branch-radio"):
                yield RadioButton("Yes", value=True)
                yield RadioButton("No")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("Delete", variant="error", id="btn-delete")

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-delete":
            radio = self.query_one("#branch-radio", RadioSet)
            delete_branch = radio.pressed_index == 0
            self.dismiss({"delete_branch": delete_branch})


class BulkDeleteDialog(ModalScreen):
    """Modal dialog for reviewing and confirming a bulk-delete set."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("x", "unmark_row", "Unmark row", show=False),
    ]

    CSS = DIALOG_BUTTON_CSS + """
    BulkDeleteDialog {
        align: center middle;
    }

    #bulk-dialog {
        width: 80;
        height: auto;
        max-height: 80%;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }

    #bulk-list {
        height: auto;
        max-height: 20;
    }
    """

    def __init__(self, entries: list[WorktreeEntry]) -> None:
        super().__init__()
        self._working: list[WorktreeEntry] = list(entries)

    def compose(self):
        with VerticalScroll(id="bulk-dialog"):
            yield Label("Bulk Delete Worktrees", classes="dialog-title")
            yield Label(self._header_text(), id="bulk-header")
            yield Label("")
            table = DataTable(cursor_type="row", id="bulk-list")
            table.add_columns("Repo", "Branch", "Path")
            yield table
            yield Label("")
            yield Checkbox("Also delete branches", value=False, id="bulk-delete-branch")
            yield Label("")
            yield Label("Press x to unmark the highlighted row.", classes="hint")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", variant="default", id="btn-bulk-cancel")
                yield Button("Delete", variant="error", id="btn-bulk-confirm")

    async def on_mount(self) -> None:
        self._populate_table()

    def _header_text(self) -> str:
        repos = {e.repo_name for e in self._working}
        return f"{len(self._working)} worktrees across {len(repos)} repos"

    def _populate_table(self) -> None:
        table = self.query_one("#bulk-list", DataTable)
        table.clear()
        for entry in self._working:
            table.add_row(entry.repo_name, entry.branch, entry.path, key=entry.id)

    def _refresh_view(self) -> None:
        self.query_one("#bulk-header", Label).update(self._header_text())
        self._populate_table()
        self.query_one("#btn-bulk-confirm", Button).disabled = len(self._working) == 0

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_unmark_row(self) -> None:
        table = self.query_one("#bulk-list", DataTable)
        if not self._working:
            return
        row = table.cursor_row
        try:
            row_key, _ = table.coordinate_to_cell_key((row, 0))
        except Exception:
            return
        target_id = str(row_key.value) if row_key is not None else None
        if target_id is None:
            return
        self._working = [e for e in self._working if e.id != target_id]
        self._refresh_view()
        if self._working:
            table.move_cursor(row=min(row, len(self._working) - 1))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-bulk-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-bulk-confirm":
            delete_branch = self.query_one("#bulk-delete-branch", Checkbox).value
            self.dismiss(
                {"entries": list(self._working), "delete_branch": delete_branch}
            )


class BulkForceDeleteDialog(ModalScreen):
    """Follow-up dialog shown when some bulk-delete entries had uncommitted changes."""

    BINDINGS = [
        Binding("escape", "skip", "Skip", show=False),
    ]

    CSS = DIALOG_BUTTON_CSS + """
    BulkForceDeleteDialog {
        align: center middle;
    }

    #force-bulk-dialog {
        width: 80;
        height: auto;
        max-height: 80%;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }

    #force-bulk-list {
        height: auto;
        max-height: 15;
    }
    """

    def __init__(self, entries: list[WorktreeEntry]) -> None:
        super().__init__()
        self._entries = entries

    def compose(self):
        with VerticalScroll(id="force-bulk-dialog"):
            yield Label("Uncommitted Changes Detected", classes="dialog-title")
            yield Label(
                f"Force delete {len(self._entries)} worktrees with uncommitted changes?",
                id="force-header",
            )
            yield Label("")
            table = DataTable(cursor_type="row", id="force-bulk-list")
            table.add_columns("Repo", "Branch", "Path")
            for entry in self._entries:
                table.add_row(entry.repo_name, entry.branch, entry.path, key=entry.id)
            yield table
            yield Label("")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Skip", variant="default", id="btn-force-skip")
                yield Button("Force All", variant="error", id="btn-force-all")

    def action_skip(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-force-skip":
            self.dismiss(False)
        elif event.button.id == "btn-force-all":
            self.dismiss(True)


class ForceDeleteDialog(ModalScreen):
    """Confirmation dialog shown when a worktree has uncommitted changes."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = DIALOG_BUTTON_CSS + """
    ForceDeleteDialog {
        align: center middle;
    }

    #force-dialog {
        width: 70;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self):
        """Compose the force delete confirmation."""
        with Vertical(id="force-dialog"):
            yield Label("Uncommitted Changes Detected", classes="dialog-title")
            yield Label("")
            yield Label(self._message)
            yield Label("")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("Force Delete", variant="error", id="btn-force")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "btn-cancel":
            self.dismiss(False)
        elif event.button.id == "btn-force":
            self.dismiss(True)
