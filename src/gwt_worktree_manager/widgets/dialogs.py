"""Modal dialog widgets for the GWT Worktree Manager TUI."""

from textual.screen import ModalScreen
from textual.widgets import Label, Input, Select, Button
from textual.containers import Vertical, Horizontal

from gwt_worktree_manager.services.worktree import VALID_WORK_TYPES, to_kebab_case
from gwt_worktree_manager.store.metadata import WorktreeEntry


class CreateDialog(ModalScreen):
    """Modal dialog for creating a new worktree."""

    CSS = """
    CreateDialog {
        align: center middle;
    }

    #create-dialog {
        width: 60;
        height: auto;
        max-height: 30;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, repos: list, config) -> None:
        super().__init__()
        self._repos = repos
        self._config = config

    def compose(self):
        """Compose the create dialog."""
        with Vertical(id="create-dialog"):
            yield Label("Create Worktree", classes="dialog-title")
            yield Label("Repository:")
            yield Select(
                [(r.name, r.name) for r in self._repos],
                id="repo-select",
                prompt="Select repository",
                allow_blank=True,
            )
            yield Label("Work Type:")
            yield Select(
                [(t, t) for t in sorted(VALID_WORK_TYPES)],
                id="type-select",
                prompt="Select type",
                allow_blank=True,
            )
            yield Label("Issue ID:")
            yield Input(placeholder="e.g., TB-123", id="issue-input")
            yield Label("Description:")
            yield Input(placeholder="Short description", id="desc-input")
            yield Label("Source Branch (leave empty for default):")
            yield Input(placeholder="main", id="source-input")
            yield Label("", id="preview-label")
            with Horizontal():
                yield Button("Create", variant="primary", id="btn-create")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update the branch preview when input changes."""
        self._update_preview()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Update the branch preview when a select changes."""
        self._update_preview()

    def _update_preview(self) -> None:
        """Compute and display a preview of the branch name."""
        try:
            type_select = self.query_one("#type-select", Select)
            work_type = type_select.value
            issue_id = self.query_one("#issue-input", Input).value
            desc = self.query_one("#desc-input", Input).value
            if (
                work_type is not Select.NULL
                and work_type
                and issue_id
                and desc
            ):
                kebab = to_kebab_case(desc)
                preview = f"Preview: {work_type}/{issue_id}-{kebab}"
                self.query_one("#preview-label", Label).update(preview)
            else:
                self.query_one("#preview-label", Label).update("")
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle create or cancel button press."""
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return

        if event.button.id == "btn-create":
            repo_select = self.query_one("#repo-select", Select)
            type_select = self.query_one("#type-select", Select)
            repo = repo_select.value
            work_type = type_select.value
            issue_id = self.query_one("#issue-input", Input).value.strip()
            desc = self.query_one("#desc-input", Input).value.strip()
            source = self.query_one("#source-input", Input).value.strip() or None

            if repo is Select.NULL or not repo:
                self.notify("Please select a repository", severity="error")
                return
            if work_type is Select.NULL or not work_type:
                self.notify("Please select a work type", severity="error")
                return
            if not issue_id:
                self.notify("Please enter an issue ID", severity="error")
                return
            if not desc:
                self.notify("Please enter a description", severity="error")
                return

            self.dismiss(
                {
                    "repo_name": repo,
                    "work_type": work_type,
                    "issue_id": issue_id,
                    "description": desc,
                    "source_branch": source,
                }
            )


class DeleteDialog(ModalScreen):
    """Modal dialog for confirming worktree deletion."""

    CSS = """
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
    """

    def __init__(self, entry: WorktreeEntry) -> None:
        super().__init__()
        self._entry = entry

    def compose(self):
        """Compose the delete confirmation dialog."""
        with Vertical(id="delete-dialog"):
            yield Label("Delete Worktree", classes="dialog-title")
            yield Label(f"Branch: {self._entry.branch}")
            yield Label(f"Repo: {self._entry.repo_name}")
            yield Label(f"Path: {self._entry.path}")
            yield Label("")
            yield Label("Are you sure you want to delete this worktree?")
            yield Label("")
            yield Label("Also delete the branch?")
            yield Select(
                [("No", False), ("Yes", True)],
                value=False,
                id="branch-select",
                allow_blank=False,
            )
            with Horizontal():
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("Delete", variant="error", id="btn-delete")

    def on_mount(self) -> None:
        """Focus the Cancel button as the safe default."""
        self.query_one("#btn-cancel").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle cancel or delete button press."""
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-delete":
            branch_select = self.query_one("#branch-select", Select)
            delete_branch = branch_select.value
            # Coerce to bool in case it is the NULL sentinel
            if delete_branch is Select.NULL:
                delete_branch = False
            self.dismiss({"delete_branch": bool(delete_branch)})
