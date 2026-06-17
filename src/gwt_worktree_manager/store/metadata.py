"""JSON-based metadata persistence for worktree entries."""

from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import re
import uuid
import warnings


@dataclass
class ReconcileResult:
    """Counts of changes applied during a reconcile.

    ``updated`` counts entries whose branch changed in place. ``added`` and
    ``removed`` count hydrated and stale entries respectively.
    """

    updated: int = 0
    added: int = 0
    removed: int = 0


@dataclass
class WorktreeEntry:
    """A worktree metadata entry."""

    id: str
    repo_name: str
    branch: str
    path: str
    issue_id: str = ""
    issue_tracker: str = ""
    issue_url: str = ""
    work_type: str = ""
    source_branch: str = ""
    created_at: str = ""
    last_accessed: str = ""
    tags: list[str] = field(default_factory=list)


# Issue ID regex: alphanumeric with optional internal hyphens
_ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$")


def extract_branch_parts(branch: str) -> tuple[str, str]:
    """Extract work_type and issue_id from a branch name.

    Expected format: type/issueId-description
    Examples:
        "feature/TB-123-add-profile" -> ("feature", "TB-123")
        "bug/12345-fix-login"        -> ("bug", "12345")
        "main"                       -> ("", "")

    Returns:
        (work_type, issue_id) tuple
    """
    if "/" not in branch:
        return ("", "")

    work_type, _, rest = branch.partition("/")
    if not rest:
        return (work_type, "")

    parts = rest.split("-")

    # Try two-part ID first (e.g., "TB-123")
    # Only treat as two-part when the first segment is not purely numeric.
    # A purely numeric first segment (e.g. "12345") is itself the full ID;
    # the following word is the description, not a continuation of the ID.
    if len(parts) >= 2 and not parts[0].isdigit():
        candidate = f"{parts[0]}-{parts[1]}"
        if _ISSUE_ID_RE.match(candidate):
            return (work_type, candidate)

    # Try single-part ID (e.g., "12345")
    if parts[0] and _ISSUE_ID_RE.match(parts[0]):
        return (work_type, parts[0])

    return (work_type, "")


class MetadataStore:
    """JSON-based metadata persistence with UUID-keyed entries."""

    def __init__(self, metadata_path: Path | None = None):
        if metadata_path:
            self._path = metadata_path
        else:
            from gwt_worktree_manager.platform_utils import get_data_dir
            self._path = get_data_dir() / "metadata.json"
        self._entries: dict[str, WorktreeEntry] = {}
        self._load()

    def _load(self) -> None:
        """Load metadata from JSON file."""
        if not self._path.exists():
            return

        self._check_permissions()

        try:
            with open(self._path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            warnings.warn(
                f"Metadata file corrupted at {self._path}. Starting fresh."
            )
            self._entries = {}
            return

        for entry_id, entry_data in data.items():
            try:
                self._entries[entry_id] = WorktreeEntry(
                    id=entry_id,
                    repo_name=entry_data.get("repo_name", ""),
                    branch=entry_data.get("branch", ""),
                    path=entry_data.get("path", ""),
                    issue_id=entry_data.get("issue_id", ""),
                    issue_tracker=entry_data.get("issue_tracker", ""),
                    issue_url=entry_data.get("issue_url", ""),
                    work_type=entry_data.get("work_type", ""),
                    source_branch=entry_data.get("source_branch", ""),
                    created_at=entry_data.get("created_at", ""),
                    last_accessed=entry_data.get("last_accessed", ""),
                    tags=entry_data.get("tags", []),
                )
            except (TypeError, KeyError):
                continue  # Skip malformed entries

    def _check_permissions(self) -> None:
        """Warn if metadata file has overly permissive permissions (Unix only)."""
        if os.name == "nt":
            return
        try:
            stat = os.stat(self._path)
            mode = stat.st_mode & 0o777
            if mode & 0o077:  # group or other has any access
                warnings.warn(
                    f"Metadata file {self._path} has permissive permissions ({oct(mode)}). "
                    f"Run: chmod 600 {self._path}"
                )
        except OSError:
            pass

    def _save(self) -> None:
        """Atomically save metadata to JSON."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = self._path.with_suffix(".tmp")

        # Remove stale temp file if exists
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass

        mode = 0o600 if os.name != "nt" else 0o666
        fd = os.open(str(temp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            try:
                os.unlink(str(temp_path))
            except OSError:
                pass
            raise

        os.replace(str(temp_path), str(self._path))

    def _to_dict(self) -> dict:
        """Convert entries to serializable dict."""
        result = {}
        for entry_id, entry in self._entries.items():
            result[entry_id] = {
                "repo_name": entry.repo_name,
                "branch": entry.branch,
                "path": entry.path,
                "issue_id": entry.issue_id,
                "issue_tracker": entry.issue_tracker,
                "issue_url": entry.issue_url,
                "work_type": entry.work_type,
                "source_branch": entry.source_branch,
                "created_at": entry.created_at,
                "last_accessed": entry.last_accessed,
                "tags": entry.tags,
            }
        return result

    # CRUD operations

    def create(self, entry: WorktreeEntry) -> None:
        """Add a new entry."""
        self._entries[entry.id] = entry
        self._save()

    def update(self, entry: WorktreeEntry) -> None:
        """Update an existing entry."""
        if entry.id not in self._entries:
            raise KeyError(f"No entry with id {entry.id}")
        self._entries[entry.id] = entry
        self._save()

    def delete(self, entry_id: str) -> None:
        """Delete an entry by ID."""
        if entry_id not in self._entries:
            raise KeyError(f"No entry with id {entry_id}")
        del self._entries[entry_id]
        self._save()

    def get(self, entry_id: str) -> WorktreeEntry | None:
        """Get an entry by ID."""
        return self._entries.get(entry_id)

    # Lookup methods

    def find_by_issue_id(self, issue_id: str) -> list[WorktreeEntry]:
        """Find all entries matching an issue ID."""
        return [e for e in self._entries.values() if e.issue_id == issue_id]

    def find_by_branch(self, branch: str) -> WorktreeEntry | None:
        """Find an entry by branch name."""
        for entry in self._entries.values():
            if entry.branch == branch:
                return entry
        return None

    def find_by_path(self, path: str) -> WorktreeEntry | None:
        """Find an entry by worktree path."""
        for entry in self._entries.values():
            if entry.path == path:
                return entry
        return None

    def list_all(self) -> list[WorktreeEntry]:
        """List all entries sorted by last_accessed descending."""
        return sorted(self._entries.values(), key=lambda e: e.last_accessed or "", reverse=True)

    # Reconciliation (FR-023, FR-024)

    def reconcile(self, git_worktrees: list, repo_name: str = "") -> ReconcileResult:
        """Reconcile metadata with Git worktree state.

        Git state is authoritative for worktree existence and for the branch
        checked out at each path. Metadata is supplementary (tags, timestamps,
        issue links).

        For a path already tracked, a changed branch updates ``branch`` and
        re-derives ``work_type``/``issue_id``; an empty re-derived ``issue_id``
        clears the now-stale ``issue_url``. ``source_branch`` and ``tags`` are
        left untouched. Pre-existing inconsistencies on an unchanged branch are
        not self-healed.

        Args:
            git_worktrees: List of WorktreeInfo from git worktree list.
                           Must have .path and .branch attributes.
            repo_name: Optional repo name to store in hydrated entries.

        Returns:
            ReconcileResult with updated/added/removed counts.
        """
        git_paths = {wt.path for wt in git_worktrees}

        # Remove stale entries (metadata exists but Git doesn't know about it)
        # Only check entries belonging to this repo to avoid deleting other repos' entries
        stale_ids = [
            entry_id
            for entry_id, entry in self._entries.items()
            if entry.path not in git_paths
            and (not repo_name or entry.repo_name == repo_name)
        ]
        for entry_id in stale_ids:
            del self._entries[entry_id]

        # Update tracked paths whose branch changed in place.
        entries_by_path = {e.path: e for e in self._entries.values()}
        updated = 0
        for wt in git_worktrees:
            entry = entries_by_path.get(wt.path)
            if entry is None:
                continue
            git_branch = wt.branch or ""
            if git_branch != entry.branch:
                self._update_entry_branch(entry, git_branch)
                updated += 1

        # Hydrate missing entries (Git knows about it but no metadata).
        # Snapshot taken before hydration so the guard reflects pre-hydrate state.
        added = 0
        existing_paths = set(entries_by_path)
        for wt in git_worktrees:
            if wt.path not in existing_paths and not getattr(wt, "is_bare", False):
                self._hydrate_entry(wt, repo_name)
                added += 1

        removed = len(stale_ids)
        if removed or added or updated:
            self._save()
        return ReconcileResult(updated=updated, added=added, removed=removed)

    def _update_entry_branch(self, entry: "WorktreeEntry", branch: str) -> None:
        """Apply a changed branch to an entry and re-derive dependent fields.

        Clears ``issue_url`` whenever the re-derived ``issue_id`` changes,
        including to empty, because the stored link belongs to the old issue.
        The async re-fetch repopulates it for a new, non-empty ``issue_id``.
        """
        entry.branch = branch
        work_type, issue_id = extract_branch_parts(branch)
        # Keep the link only when the issue is non-empty and unchanged;
        # otherwise it is stale (different issue) or impossible (no issue).
        if not issue_id or issue_id != entry.issue_id:
            entry.issue_url = ""
        entry.work_type = work_type
        entry.issue_id = issue_id

    def _hydrate_entry(self, wt, repo_name: str = "") -> None:
        """Create a metadata entry from a Git worktree.

        Extracts issue_id and work_type from branch name.
        """
        branch = wt.branch or ""
        work_type, issue_id = extract_branch_parts(branch)

        now = datetime.now(timezone.utc).isoformat()
        entry = WorktreeEntry(
            id=str(uuid.uuid4()),
            repo_name=repo_name,
            branch=branch,
            path=wt.path,
            issue_id=issue_id,
            work_type=work_type,
            source_branch="",
            created_at=now,
            last_accessed=now,
            tags=[],
        )
        self._entries[entry.id] = entry
