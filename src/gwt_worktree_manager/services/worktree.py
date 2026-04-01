"""Core orchestrator service for worktree management."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import re
import shutil
import uuid

from gwt_worktree_manager.config.manager import Config
from gwt_worktree_manager.store.metadata import MetadataStore, WorktreeEntry
from gwt_worktree_manager.services.discovery import RepoDiscovery
from gwt_worktree_manager.git import operations as git


# ==============================================================================
# Custom exceptions
# ==============================================================================


class WorktreeError(Exception):
    """Base exception for worktree service errors."""


class WorktreeNotFoundError(WorktreeError):
    """Raised when a worktree ID doesn't exist in metadata."""


class BranchExistsError(WorktreeError):
    """Raised when trying to create a branch that already exists."""


class InvalidInputError(WorktreeError):
    """Raised for validation failures (bad issue ID, work type, etc.)."""


class UncommittedChangesError(WorktreeError):
    """Raised when operation requires clean worktree but changes exist."""


class BranchCheckedOutError(WorktreeError):
    """Raised when target branch is already checked out in another worktree."""


# ==============================================================================
# OpenResult dataclass
# ==============================================================================


@dataclass
class OpenResult:
    """Result of opening a worktree."""

    worktree: WorktreeEntry
    action: Literal["cd", "command"]
    cd_path: Path | None = None
    command_executed: str | None = None


# ==============================================================================
# Helper functions
# ==============================================================================

VALID_WORK_TYPES = {"feature", "bug", "chore", "doc", "refactor", "hotfix"}
_ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$")


def to_kebab_case(text: str) -> str:
    """Convert text to kebab-case for branch names."""
    text = text.lower().strip()
    text = re.sub(r"[\s_/:]+", "-", text)        # Replace separators with hyphens
    text = re.sub(r"[^a-z0-9-]", "", text)       # Remove remaining special chars
    text = re.sub(r"-+", "-", text)              # Collapse consecutive hyphens
    text = text.strip("-")                        # Remove leading/trailing hyphens
    return text


def generate_branch_name(work_type: str, issue_id: str, description: str) -> str:
    """Generate a branch name from components.

    Format: type/issueId-kebab-description
    Example: feature/TB-123-add-user-profile
    """
    kebab = to_kebab_case(description)
    if not kebab:
        raise InvalidInputError(
            "Description produced an empty branch slug after conversion"
        )
    branch = f"{work_type}/{issue_id}-{kebab}"
    if len(branch) >= 200:
        raise InvalidInputError(
            f"Branch name too long ({len(branch)} chars, must be under 200)"
        )
    return branch


def validate_work_type(work_type: str) -> None:
    """Validate work type is one of the allowed values."""
    if work_type not in VALID_WORK_TYPES:
        raise InvalidInputError(
            f"Invalid work type '{work_type}'. Must be one of: "
            f"{', '.join(sorted(VALID_WORK_TYPES))}"
        )


def validate_issue_id(issue_id: str) -> None:
    """Validate issue ID format."""
    if not issue_id:
        raise InvalidInputError("Issue ID cannot be empty")
    if not _ISSUE_ID_RE.match(issue_id):
        raise InvalidInputError(
            f"Issue ID '{issue_id}' is invalid. "
            "Must be alphanumeric with optional internal hyphens."
        )


# ==============================================================================
# WorktreeService
# ==============================================================================


class WorktreeService:
    """Core orchestrator that creates, manages, and tracks worktrees."""

    def __init__(
        self,
        config: Config,
        metadata: MetadataStore,
        discovery: RepoDiscovery,
    ) -> None:
        self._config = config
        self._metadata = metadata
        self._discovery = discovery

    async def create_worktree(
        self,
        repo_name: str,
        work_type: str,
        issue_id: str,
        description: str,
        source_branch: str | None = None,
    ) -> WorktreeEntry:
        """Create a new worktree with a new branch."""
        # 1. Validate inputs
        validate_work_type(work_type)
        validate_issue_id(issue_id)
        git.validate_branch_name(f"{work_type}/{issue_id}")

        # 2. Find repo
        repo_path = await self._resolve_repo(repo_name)

        # 3. Determine source branch
        repo_config = self._config.get_repo_config(repo_name)
        if source_branch is None:
            source_branch = (
                repo_config.source_branch or self._config.default_source_branch
            )

        # 4. Validate source branch exists
        if not await git.branch_exists(repo_path, source_branch):
            raise InvalidInputError(
                f"Source branch '{source_branch}' not found in {repo_name}"
            )

        # 5. Generate branch name
        branch_name = generate_branch_name(work_type, issue_id, description)

        # 6. Check branch uniqueness
        if await git.branch_exists(repo_path, branch_name):
            raise BranchExistsError(
                f"Branch '{branch_name}' already exists in {repo_name}"
            )

        # 7. Create worktree path
        worktrees_dir = self._config.resolve_worktrees_dir()
        worktree_path = worktrees_dir / repo_name / branch_name

        # 8. Create worktree
        try:
            await git.create_worktree(
                repo_path, branch_name, worktree_path, source_branch
            )
        except git.GitError:
            await git.prune_worktrees(repo_path)
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
            raise

        # 9. Create metadata entry
        now = datetime.now(timezone.utc).isoformat()
        entry = WorktreeEntry(
            id=str(uuid.uuid4()),
            repo_name=repo_name,
            branch=branch_name,
            path=str(worktree_path),
            issue_id=issue_id,
            work_type=work_type,
            source_branch=source_branch,
            created_at=now,
            last_accessed=now,
            tags=[],
        )
        self._metadata.create(entry)
        return entry

    async def delete_worktree(
        self, worktree_id: str, delete_branch: bool = False
    ) -> None:
        """Delete a worktree and optionally its branch."""
        entry = self._metadata.get(worktree_id)
        if entry is None:
            raise WorktreeNotFoundError(f"No worktree with id {worktree_id}")

        repo_path = await self._resolve_repo(entry.repo_name)
        worktree_path = Path(entry.path)

        if worktree_path.exists():
            status = await git.get_worktree_status(worktree_path)
            if status.strip():
                await git.remove_worktree(repo_path, worktree_path, force=True)
            else:
                await git.remove_worktree(repo_path, worktree_path)
        else:
            await git.prune_worktrees(repo_path)

        if delete_branch and entry.branch:
            try:
                await git.delete_branch(repo_path, entry.branch, force=True)
            except git.GitError:
                pass

        self._metadata.delete(worktree_id)

    async def open_worktree(self, worktree_id: str) -> OpenResult:
        """Open a worktree using the configured action."""
        entry = self._metadata.get(worktree_id)
        if entry is None:
            raise WorktreeNotFoundError(f"No worktree with id {worktree_id}")

        entry.last_accessed = datetime.now(timezone.utc).isoformat()
        self._metadata.update(entry)

        repo_config = self._config.get_repo_config(entry.repo_name)
        open_command = repo_config.open_command
        worktree_path = Path(entry.path)

        if open_command == "cd":
            return OpenResult(
                worktree=entry,
                action="cd",
                cd_path=worktree_path,
            )
        return OpenResult(
            worktree=entry,
            action="command",
            command_executed=open_command,
        )

    async def move_worktree(
        self, worktree_id: str, new_path: Path
    ) -> WorktreeEntry:
        """Move a worktree to a new filesystem path."""
        entry = self._metadata.get(worktree_id)
        if entry is None:
            raise WorktreeNotFoundError(f"No worktree with id {worktree_id}")

        repo_path = await self._resolve_repo(entry.repo_name)
        old_path = Path(entry.path)

        if old_path.exists():
            status = await git.get_worktree_status(old_path)
            if status.strip():
                raise UncommittedChangesError(
                    f"Worktree at {old_path} has uncommitted changes. "
                    "Use --force to override."
                )

        await git.move_worktree(repo_path, old_path, new_path)

        entry.path = str(new_path)
        entry.last_accessed = datetime.now(timezone.utc).isoformat()
        self._metadata.update(entry)
        return entry

    async def switch_branch(
        self, worktree_id: str, branch: str
    ) -> WorktreeEntry:
        """Switch the branch of a worktree."""
        entry = self._metadata.get(worktree_id)
        if entry is None:
            raise WorktreeNotFoundError(f"No worktree with id {worktree_id}")

        repo_path = await self._resolve_repo(entry.repo_name)
        worktree_path = Path(entry.path)

        if not await git.branch_exists(repo_path, branch, check_remote=False):
            raise InvalidInputError(
                f"Branch '{branch}' not found locally. "
                f"Try: git fetch && git branch {branch} origin/{branch}"
            )

        status = await git.get_worktree_status(worktree_path)
        if status.strip():
            raise UncommittedChangesError(
                f"Worktree at {worktree_path} has uncommitted changes."
            )

        all_worktrees = await git.list_worktrees(repo_path)
        for wt in all_worktrees:
            if wt.branch == branch and wt.path != str(worktree_path):
                raise BranchCheckedOutError(
                    f"Branch '{branch}' is already checked out in worktree "
                    f"at {wt.path}"
                )

        await git.checkout_branch(worktree_path, branch)

        entry.branch = branch
        entry.last_accessed = datetime.now(timezone.utc).isoformat()
        self._metadata.update(entry)
        return entry

    async def list_worktrees(
        self, repo_name: str | None = None
    ) -> list[WorktreeEntry]:
        """List all worktrees, optionally filtered by repo."""
        entries = self._metadata.list_all()
        if repo_name:
            entries = [e for e in entries if e.repo_name == repo_name]
        return entries

    async def search_by_issue(self, issue_id: str) -> list[WorktreeEntry]:
        """Search for worktrees by issue ID across all repos."""
        return self._metadata.find_by_issue_id(issue_id)

    async def _resolve_repo(self, repo_name: str) -> Path:
        """Find the path for a repo by name."""
        repos = await self._discovery.discover_repos()
        for repo in repos:
            if repo.name == repo_name:
                return repo.path
        raise WorktreeNotFoundError(f"Repository '{repo_name}' not found")
