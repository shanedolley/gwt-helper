import subprocess
from pathlib import Path

import pytest

from gwt_worktree_manager.config.manager import Config
from gwt_worktree_manager.services.discovery import RepoDiscovery


@pytest.fixture
def scan_dir(tmp_path: Path) -> Path:
    """Create a directory structure with multiple git repos at various depths."""
    for name in ["repo-a", "repo-b"]:
        repo = tmp_path / name
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    nested = tmp_path / "org" / "repo-c"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", str(nested)], check=True, capture_output=True)

    (tmp_path / "not-a-repo").mkdir()
    (tmp_path / "not-a-repo" / "file.txt").write_text("hello")

    return tmp_path


class TestRepoDiscovery:
    @pytest.mark.asyncio
    async def test_discovers_repos_at_depth_1(self, scan_dir: Path) -> None:
        config = Config(scan_paths=[str(scan_dir)], scan_depth=3)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        names = [r.name for r in repos]
        assert "repo-a" in names
        assert "repo-b" in names

    @pytest.mark.asyncio
    async def test_discovers_repos_at_depth_2(self, scan_dir: Path) -> None:
        config = Config(scan_paths=[str(scan_dir)], scan_depth=3)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        names = [r.name for r in repos]
        assert "repo-c" in names

    @pytest.mark.asyncio
    async def test_excludes_non_git_directories(self, scan_dir: Path) -> None:
        config = Config(scan_paths=[str(scan_dir)], scan_depth=3)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        names = [r.name for r in repos]
        assert "not-a-repo" not in names

    @pytest.mark.asyncio
    async def test_respects_scan_depth_limit(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "deep-repo"
        deep.mkdir(parents=True)
        subprocess.run(["git", "init", str(deep)], check=True, capture_output=True)

        config = Config(scan_paths=[str(tmp_path)], scan_depth=2)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        names = [r.name for r in repos]
        assert "deep-repo" not in names

    @pytest.mark.asyncio
    async def test_excludes_worktrees_dir(self, tmp_path: Path) -> None:
        worktrees = tmp_path / "worktrees"
        repo_in_wt = worktrees / "some-repo"
        repo_in_wt.mkdir(parents=True)
        subprocess.run(["git", "init", str(repo_in_wt)], check=True, capture_output=True)

        config = Config(
            scan_paths=[str(tmp_path)],
            scan_depth=3,
            worktrees_dir=str(worktrees),
        )
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        names = [r.name for r in repos]
        assert "some-repo" not in names

    @pytest.mark.asyncio
    async def test_excludes_worktree_directories(self, tmp_path: Path) -> None:
        """Directories where .git is a file (worktrees) should be excluded."""
        main_repo = tmp_path / "main-repo"
        main_repo.mkdir()
        subprocess.run(["git", "init", str(main_repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(main_repo), "config", "user.email", "t@t.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(main_repo), "config", "user.name", "T"],
            check=True,
            capture_output=True,
        )
        (main_repo / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(main_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(main_repo), "commit", "-m", "init"],
            check=True,
            capture_output=True,
        )

        result = subprocess.run(
            ["git", "-C", str(main_repo), "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        default_branch = result.stdout.strip()

        wt_dir = tmp_path / "wt-checkout"
        subprocess.run(
            ["git", "-C", str(main_repo), "worktree", "add", "-b", "feat", str(wt_dir), default_branch],
            check=True,
            capture_output=True,
        )

        config = Config(
            scan_paths=[str(tmp_path)],
            scan_depth=3,
            worktrees_dir=str(tmp_path / "nonexistent"),
        )
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        names = [r.name for r in repos]
        assert "main-repo" in names
        assert "wt-checkout" not in names

    @pytest.mark.asyncio
    async def test_skips_symlinks(self, tmp_path: Path) -> None:
        repo = tmp_path / "real-repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

        link = tmp_path / "link-repo"
        link.symlink_to(repo)

        config = Config(scan_paths=[str(tmp_path)], scan_depth=3)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        names = [r.name for r in repos]
        assert "real-repo" in names
        assert "link-repo" not in names

    @pytest.mark.asyncio
    async def test_empty_scan_path(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        config = Config(scan_paths=[str(empty)], scan_depth=3)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        assert repos == []

    @pytest.mark.asyncio
    async def test_nonexistent_scan_path(self, tmp_path: Path) -> None:
        config = Config(scan_paths=[str(tmp_path / "does-not-exist")], scan_depth=3)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        assert repos == []

    @pytest.mark.asyncio
    async def test_results_sorted_by_name(self, scan_dir: Path) -> None:
        config = Config(scan_paths=[str(scan_dir)], scan_depth=3)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        names = [r.name for r in repos]
        assert names == sorted(names, key=str.lower)

    @pytest.mark.asyncio
    async def test_multiple_scan_paths(self, tmp_path: Path) -> None:
        path_a = tmp_path / "area-a"
        path_b = tmp_path / "area-b"

        repo_a = path_a / "repo-x"
        repo_b = path_b / "repo-y"
        repo_a.mkdir(parents=True)
        repo_b.mkdir(parents=True)
        subprocess.run(["git", "init", str(repo_a)], check=True, capture_output=True)
        subprocess.run(["git", "init", str(repo_b)], check=True, capture_output=True)

        config = Config(scan_paths=[str(path_a), str(path_b)], scan_depth=3)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        names = [r.name for r in repos]
        assert "repo-x" in names
        assert "repo-y" in names

    @pytest.mark.asyncio
    async def test_repo_paths_are_absolute(self, scan_dir: Path) -> None:
        config = Config(scan_paths=[str(scan_dir)], scan_depth=3)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        for repo in repos:
            assert repo.path.is_absolute()

    @pytest.mark.asyncio
    async def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        hidden = tmp_path / ".hidden-repo"
        hidden.mkdir()
        subprocess.run(["git", "init", str(hidden)], check=True, capture_output=True)

        config = Config(scan_paths=[str(tmp_path)], scan_depth=3)
        discovery = RepoDiscovery(config)
        repos = await discovery.discover_repos()
        names = [r.name for r in repos]
        assert ".hidden-repo" not in names
