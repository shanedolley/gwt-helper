"""Core orchestrator service for worktree management."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal
import re
import shutil
import uuid

import asyncio

from gwt_worktree_manager.config.manager import Config
from gwt_worktree_manager.store.metadata import MetadataStore, WorktreeEntry, _ISSUE_ID_RE
from gwt_worktree_manager.services.discovery import RepoDiscovery
from gwt_worktree_manager.git import operations as git
from gwt_worktree_manager.integrations import IssueCache, IssueInfo
from gwt_worktree_manager.integrations.linear import LinearClient
from gwt_worktree_manager.integrations.ado import ADOClient


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


@dataclass
class BulkDeleteResult:
    """Aggregated outcome of a bulk delete run."""

    succeeded: list[str]
    dirty: list[WorktreeEntry]
    failed: list[tuple[str, Exception]]


# ==============================================================================
# Helper functions
# ==============================================================================

VALID_WORK_TYPES = {"feature", "bug", "chore", "doc", "refactor", "hotfix", "task", "pr-review"}


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

    Format with issue ID: type/issueId-kebab-description
    Format without:       type/kebab-description
    Examples:
        feature/TB-123-add-user-profile
        chore/update-dependencies
    """
    kebab = to_kebab_case(description)
    if not kebab:
        raise InvalidInputError(
            "Description produced an empty branch slug after conversion"
        )
    if issue_id:
        branch = f"{work_type}/{issue_id}-{kebab}"
    else:
        branch = f"{work_type}/{kebab}"
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
        self._issue_cache = IssueCache(ttl_seconds=config.cache_ttl)
        self._linear_client = LinearClient.from_config(config.linear.api_key_env, self._issue_cache) if config.linear.enabled else None
        self._ado_client = ADOClient.from_config(config.ado.org_url_env, config.ado.pat_env, self._issue_cache) if config.ado.enabled else None

    async def create_worktree(
        self,
        repo_name: str,
        work_type: str,
        issue_id: str,
        description: str,
        source_branch: str | None = None,
        issue_tracker: str = "",
        issue_url: str = "",
    ) -> WorktreeEntry:
        """Create a new worktree with a new branch."""
        # 1. Validate inputs
        validate_work_type(work_type)
        if issue_id:
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
        if ".." in branch_name:
            raise InvalidInputError("Branch name cannot contain '..'")
        worktrees_dir = self._config.resolve_worktrees_dir()
        worktree_path = worktrees_dir / repo_name / branch_name
        try:
            worktree_path.resolve().relative_to(worktrees_dir.resolve())
        except ValueError:
            raise InvalidInputError(
                "Worktree path would escape the configured worktrees directory"
            )

        # 8. Create worktree
        try:
            await git.create_worktree(
                repo_path, branch_name, worktree_path, source_branch
            )
        except (git.GitError, KeyboardInterrupt):
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
            issue_tracker=issue_tracker,
            issue_url=issue_url,
            work_type=work_type,
            source_branch=source_branch,
            created_at=now,
            last_accessed=now,
            tags=[],
        )
        self._metadata.create(entry)
        return entry

    async def create_pr_review_worktree(
        self,
        repo_name: str,
        pr_number: str,
    ) -> WorktreeEntry:
        """Create a worktree for reviewing a pull request."""
        repo_path = await self._resolve_repo(repo_name)

        # Resolve PR branch name via gh CLI
        branch_name = await self._resolve_pr_branch(repo_path, pr_number)

        # Fetch the branch from origin
        await git.fetch_branch(repo_path, branch_name)

        # Build worktree path: worktrees_dir/repo_name/pr-review/PR#
        worktrees_dir = self._config.resolve_worktrees_dir()
        worktree_path = worktrees_dir / repo_name / "pr-review" / pr_number
        try:
            worktree_path.resolve().relative_to(worktrees_dir.resolve())
        except ValueError:
            raise InvalidInputError(
                "Worktree path would escape the configured worktrees directory"
            )

        # Create worktree using existing branch (no -b flag)
        try:
            await git.create_worktree_existing_branch(
                repo_path, branch_name, worktree_path
            )
        except (git.GitError, KeyboardInterrupt):
            await git.prune_worktrees(repo_path)
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
            raise

        # Create metadata entry
        now = datetime.now(timezone.utc).isoformat()
        entry = WorktreeEntry(
            id=str(uuid.uuid4()),
            repo_name=repo_name,
            branch=branch_name,
            path=str(worktree_path),
            issue_id=pr_number,
            issue_tracker="",
            issue_url="",
            work_type="pr-review",
            source_branch="",
            created_at=now,
            last_accessed=now,
            tags=[],
        )
        self._metadata.create(entry)
        return entry

    async def _resolve_pr_branch(self, repo_path: Path, pr_number: str) -> str:
        """Resolve a PR number to its source branch name using gh CLI."""
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
                raise InvalidInputError(
                    f"Failed to resolve PR #{pr_number}: {stderr.decode().strip()}"
                )
            branch = stdout.decode().strip()
            if not branch:
                raise InvalidInputError(
                    f"PR #{pr_number} has no branch name"
                )
            return branch
        except FileNotFoundError:
            raise InvalidInputError(
                "gh CLI not found. Install it: https://cli.github.com"
            )
        except asyncio.TimeoutError:
            raise InvalidInputError(
                f"Timed out resolving PR #{pr_number}"
            )

    async def delete_worktree(
        self, worktree_id: str, delete_branch: bool = False, force: bool = False
    ) -> None:
        """Delete a worktree and optionally its branch."""
        entry = self._metadata.get(worktree_id)
        if entry is None:
            raise WorktreeNotFoundError(f"No worktree with id {worktree_id}")

        repo_path = await self._resolve_repo(entry.repo_name)
        worktree_path = Path(entry.path)

        if worktree_path.exists():
            status = await git.get_worktree_status(worktree_path)
            if status.strip() and not force:
                raise UncommittedChangesError(
                    f"Worktree at {worktree_path} has uncommitted changes. Use --force to override."
                )
            await git.remove_worktree(repo_path, worktree_path, force=bool(status.strip()))
        else:
            await git.prune_worktrees(repo_path)

        if delete_branch and entry.branch:
            try:
                await git.delete_branch(repo_path, entry.branch, force=True)
            except git.GitError as e:
                import warnings
                warnings.warn(f"Failed to delete branch {entry.branch}: {e}")

        self._metadata.delete(worktree_id)

    async def delete_worktrees_bulk(
        self,
        entries: list[WorktreeEntry],
        *,
        delete_branch: bool,
        force: bool = False,
        on_progress: "Callable[[int, int, WorktreeEntry], None] | None" = None,
    ) -> "BulkDeleteResult":
        """Delete a batch of worktrees, continuing past individual failures.

        Returns a BulkDeleteResult partitioning outcomes into succeeded
        (including worktrees that were already gone), dirty (raised
        UncommittedChangesError), and failed (all other exceptions).

        ``on_progress`` is called before each entry is processed with
        ``(index_1_based, total, entry)`` so callers can surface progress
        in a status bar. Exceptions raised by the callback are swallowed
        so progress reporting cannot break the batch.

        The bare ``except Exception`` below is intentional: it ensures
        per-entry errors are collected into ``result.failed`` rather than
        aborting the batch. BaseException subclasses such as
        KeyboardInterrupt, SystemExit, and asyncio.CancelledError still
        propagate, so task cancellation remains responsive.
        """
        result = BulkDeleteResult(succeeded=[], dirty=[], failed=[])
        total = len(entries)
        for i, entry in enumerate(entries, start=1):
            if on_progress is not None:
                try:
                    on_progress(i, total, entry)
                except Exception:  # noqa: BLE001 — progress must not crash the batch
                    pass
            if not entry.id:
                result.failed.append(
                    (entry.id or "<no-id>", ValueError("entry missing id"))
                )
                continue
            try:
                await self.delete_worktree(
                    entry.id, delete_branch=delete_branch, force=force
                )
                result.succeeded.append(entry.id)
            except WorktreeNotFoundError:
                result.succeeded.append(entry.id)
            except UncommittedChangesError:
                result.dirty.append(entry)
            except Exception as exc:  # noqa: BLE001 — see docstring
                result.failed.append((entry.id, exc))
        return result

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

    @property
    def config(self) -> Config:
        return self._config

    @property
    def metadata(self) -> MetadataStore:
        return self._metadata

    async def reconcile_all_repos(self) -> None:
        """Discover repos and reconcile metadata with Git state."""
        repos = await self._discovery.discover_repos()
        for repo in repos:
            try:
                worktrees = await git.list_worktrees(repo.path)
                self._metadata.reconcile(worktrees, repo_name=repo.name)
            except git.GitError:
                pass

    async def get_discovered_repos(self):
        """Return discovered repos."""
        return await self._discovery.discover_repos()

    async def get_issue_info(self, issue_id: str) -> "IssueInfo | None":
        """Try to fetch issue info from Linear then ADO."""
        if not issue_id:
            return None
        if self._linear_client:
            info = await self._linear_client.get_issue(issue_id)
            if info:
                return info
        if self._ado_client:
            info = await self._ado_client.get_work_item(issue_id)
            if info:
                return info
        return None

    async def _resolve_repo(self, repo_name: str) -> Path:
        """Find the path for a repo by name."""
        repos = await self._discovery.discover_repos()
        for repo in repos:
            if repo.name == repo_name:
                return repo.path
        raise WorktreeNotFoundError(f"Repository '{repo_name}' not found")
