from dataclasses import dataclass
from pathlib import Path
import time

from gwt_worktree_manager.config.manager import Config


@dataclass
class DiscoveredRepo:
    """A discovered Git repository."""

    name: str
    path: Path
    org: str = ""


class RepoDiscovery:
    """Discovers Git repositories by scanning configured paths."""

    def __init__(self, config: Config) -> None:
        self._scan_paths = config.resolve_scan_paths()
        self._scan_depth = config.scan_depth
        self._worktrees_dir = config.resolve_worktrees_dir()
        self._cached_repos: list[DiscoveredRepo] | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = 60  # 60 seconds

    async def discover_repos(self, force_refresh: bool = False) -> list[DiscoveredRepo]:
        """Scan all configured paths for Git repositories.

        Returns repos sorted by name. Excludes:
        - Directories under worktrees_dir
        - Directories that are themselves worktrees (.git is a file, not a dir)
        - Symlinks (to prevent loops)
        """
        if not force_refresh and self._cached_repos is not None:
            if time.time() - self._cache_time < self._cache_ttl:
                return self._cached_repos

        repos: list[DiscoveredRepo] = []
        for scan_path in self._scan_paths:
            if scan_path.exists() and scan_path.is_dir():
                self._scan_directory(scan_path, 0, repos)

        repos.sort(key=lambda r: r.name.lower())
        self._cached_repos = repos
        self._cache_time = time.time()
        return repos

    def _scan_directory(
        self,
        directory: Path,
        depth: int,
        repos: list[DiscoveredRepo],
        scan_root: Path | None = None,
    ) -> None:
        """Recursively scan a directory for Git repos."""
        if depth > self._scan_depth:
            return

        if scan_root is None:
            scan_root = directory

        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return
        except OSError:
            return

        for entry in entries:
            if not entry.is_dir() or entry.is_symlink():
                continue

            if entry.name.startswith(".") and entry.name != ".git":
                continue

            try:
                resolved = entry.resolve()
                worktrees_resolved = self._worktrees_dir.resolve()
                try:
                    resolved.relative_to(worktrees_resolved)
                    continue
                except ValueError:
                    pass
            except OSError:
                continue

            git_dir = entry / ".git"
            if git_dir.exists():
                if git_dir.is_dir():
                    try:
                        rel = entry.resolve().parent.relative_to(scan_root.resolve())
                        org = str(rel) if str(rel) != "." else ""
                    except ValueError:
                        org = ""
                    repos.append(DiscoveredRepo(
                        name=entry.name,
                        path=entry.resolve(),
                        org=org,
                    ))
                continue

            if depth < self._scan_depth:
                self._scan_directory(entry, depth + 1, repos, scan_root)
