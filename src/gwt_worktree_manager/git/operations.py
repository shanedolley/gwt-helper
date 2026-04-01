"""Git subprocess abstraction layer for worktree management."""

from dataclasses import dataclass
from pathlib import Path
import asyncio
import re


class GitError(Exception):
    """Raised when a Git command fails."""

    def __init__(self, command: list[str], stderr: str, returncode: int):
        self.command = command
        self.stderr = stderr
        self.returncode = returncode
        super().__init__(f"Git command failed (exit {returncode}): {stderr.strip()}")


class GitNotFoundError(GitError):
    """Raised when Git binary is not found."""

    def __init__(self):
        super().__init__(["git"], "git: command not found", 127)


class GitVersionError(Exception):
    """Raised when Git version is too old."""

    def __init__(self, version: str, minimum: str = "2.20.0"):
        self.version = version
        self.minimum = minimum
        super().__init__(f"Git {version} is too old. Minimum required: {minimum}")


@dataclass
class WorktreeInfo:
    """Parsed worktree from git worktree list --porcelain."""

    path: str
    head: str
    branch: str | None = None  # None for detached HEAD
    is_bare: bool = False
    is_locked: bool = False
    is_prunable: bool = False


# Branch name validation pattern - reject shell metacharacters
_SAFE_BRANCH_RE = re.compile(r"^[a-zA-Z0-9._/\-]+$")


def validate_branch_name(branch: str) -> None:
    """Validate a branch name is safe for subprocess use."""
    if not branch:
        raise ValueError("Branch name cannot be empty")
    if not _SAFE_BRANCH_RE.match(branch):
        raise ValueError(f"Branch name contains invalid characters: {branch}")
    if branch.startswith("-"):
        raise ValueError(f"Branch name cannot start with a dash: {branch}")


async def run_git_command(
    args: list[str],
    cwd: Path | None = None,
    timeout: float = 30.0,
) -> tuple[str, str, int]:
    """Run a git command and return (stdout, stderr, returncode).

    Uses argument list — never shell=True.
    Raises GitNotFoundError if git binary is not found.
    Raises GitError if the command times out.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise GitError(["git"] + list(args), f"Command timed out after {timeout}s", -1)
        return stdout.decode(), stderr.decode(), proc.returncode
    except FileNotFoundError:
        raise GitNotFoundError()


async def create_worktree(
    repo_path: Path,
    branch: str,
    worktree_path: Path,
    source_branch: str,
) -> None:
    """Create a new worktree with a new branch from source_branch."""
    args = ["worktree", "add", "-b", branch, str(worktree_path), source_branch]
    stdout, stderr, code = await run_git_command(args, cwd=repo_path)
    if code != 0:
        raise GitError(args, stderr, code)


async def create_worktree_existing_branch(
    repo_path: Path,
    branch: str,
    worktree_path: Path,
) -> None:
    """Create a worktree for an existing branch (no new branch created)."""
    args = ["worktree", "add", str(worktree_path), branch]
    stdout, stderr, code = await run_git_command(args, cwd=repo_path)
    if code != 0:
        raise GitError(args, stderr, code)


async def fetch_branch(repo_path: Path, branch: str) -> None:
    """Fetch a specific branch from origin."""
    args = ["fetch", "origin", branch]
    stdout, stderr, code = await run_git_command(args, cwd=repo_path)
    if code != 0:
        raise GitError(args, stderr, code)


async def list_worktrees(repo_path: Path) -> list[WorktreeInfo]:
    """List all worktrees for a repo using porcelain output."""
    args = ["worktree", "list", "--porcelain"]
    stdout, stderr, code = await run_git_command(args, cwd=repo_path)
    if code != 0:
        raise GitError(args, stderr, code)
    return parse_worktree_list(stdout)


async def remove_worktree(
    repo_path: Path,
    worktree_path: Path,
    force: bool = False,
) -> None:
    """Remove a worktree."""
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree_path))
    stdout, stderr, code = await run_git_command(args, cwd=repo_path)
    if code != 0:
        raise GitError(args, stderr, code)


async def move_worktree(
    repo_path: Path,
    old_path: Path,
    new_path: Path,
) -> None:
    """Move a worktree to a new directory."""
    args = ["worktree", "move", str(old_path), str(new_path)]
    stdout, stderr, code = await run_git_command(args, cwd=repo_path)
    if code != 0:
        raise GitError(args, stderr, code)


async def prune_worktrees(repo_path: Path) -> None:
    """Prune stale worktree references."""
    args = ["worktree", "prune"]
    stdout, stderr, code = await run_git_command(args, cwd=repo_path)
    if code != 0:
        raise GitError(args, stderr, code)


async def list_branches(
    repo_path: Path,
    include_remote: bool = False,
) -> list[str]:
    """List branch names."""
    args = ["branch", "--list", "--format=%(refname:short)"]
    if include_remote:
        args.insert(1, "-a")
    stdout, stderr, code = await run_git_command(args, cwd=repo_path)
    if code != 0:
        raise GitError(args, stderr, code)
    return [b.strip() for b in stdout.strip().split("\n") if b.strip()]


async def branch_exists(
    repo_path: Path,
    branch: str,
    check_remote: bool = True,
) -> bool:
    """Check if a branch exists locally or remotely."""
    stdout, stderr, code = await run_git_command(
        ["branch", "--list", branch],
        cwd=repo_path,
    )
    if stdout.strip():
        return True

    if check_remote:
        stdout, stderr, code = await run_git_command(
            ["branch", "-r", "--list", f"*/{branch}"],
            cwd=repo_path,
        )
        if stdout.strip():
            return True

    return False


async def delete_branch(
    repo_path: Path,
    branch: str,
    force: bool = False,
) -> None:
    """Delete a local branch."""
    flag = "-D" if force else "-d"
    args = ["branch", flag, branch]
    stdout, stderr, code = await run_git_command(args, cwd=repo_path)
    if code != 0:
        raise GitError(args, stderr, code)


async def checkout_branch(
    worktree_path: Path,
    branch: str,
) -> None:
    """Checkout a branch in a worktree."""
    args = ["-C", str(worktree_path), "checkout", branch]
    stdout, stderr, code = await run_git_command(args)
    if code != 0:
        raise GitError(["checkout", branch], stderr, code)


async def get_worktree_status(worktree_path: Path) -> str:
    """Get porcelain status of a worktree."""
    args = ["-C", str(worktree_path), "status", "--porcelain"]
    stdout, stderr, code = await run_git_command(args)
    if code != 0:
        raise GitError(["status"], stderr, code)
    return stdout


async def get_current_branch(worktree_path: Path) -> str:
    """Get the current branch name of a worktree."""
    args = ["-C", str(worktree_path), "rev-parse", "--abbrev-ref", "HEAD"]
    stdout, stderr, code = await run_git_command(args)
    if code != 0:
        raise GitError(["rev-parse"], stderr, code)
    return stdout.strip()


async def get_git_version() -> str:
    """Get the Git version string (e.g., '2.39.0')."""
    stdout, stderr, code = await run_git_command(["--version"])
    if code != 0:
        raise GitError(["--version"], stderr, code)
    # Parse "git version 2.39.0" or "git version 2.39.0 (Apple Git-143)"
    match = re.search(r"(\d+\.\d+\.\d+)", stdout)
    if not match:
        raise GitError(["--version"], f"Cannot parse version: {stdout}", 1)
    return match.group(1)


async def check_git_version(minimum: str = "2.20.0") -> str:
    """Check that Git meets minimum version requirement. Returns version string."""
    version = await get_git_version()
    version_parts = [int(x) for x in version.split(".")]
    minimum_parts = [int(x) for x in minimum.split(".")]
    if version_parts < minimum_parts:
        raise GitVersionError(version, minimum)
    return version


def parse_worktree_list(output: str) -> list[WorktreeInfo]:
    """Parse output of `git worktree list --porcelain`.

    Format:
        worktree /path/to/worktree
        HEAD abc123...
        branch refs/heads/main

        worktree /path/to/other
        HEAD def456...
        detached

    Blocks are separated by blank lines.
    """
    worktrees = []
    current: dict = {}

    for line in output.split("\n"):
        line = line.strip()
        if not line:
            if current:
                worktrees.append(_build_worktree_info(current))
                current = {}
            continue

        if line.startswith("worktree "):
            current["path"] = line[9:]
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            # branch refs/heads/main -> main
            ref = line[7:]
            if ref.startswith("refs/heads/"):
                current["branch"] = ref[11:]
            else:
                current["branch"] = ref
        elif line == "bare":
            current["bare"] = True
        elif line == "detached":
            current["detached"] = True
        elif line.startswith("locked"):
            current["locked"] = True
        elif line.startswith("prunable"):
            current["prunable"] = True

    # Don't forget last block
    if current:
        worktrees.append(_build_worktree_info(current))

    return worktrees


def _build_worktree_info(data: dict) -> WorktreeInfo:
    """Build WorktreeInfo from parsed porcelain data."""
    return WorktreeInfo(
        path=data.get("path", ""),
        head=data.get("head", ""),
        branch=data.get("branch"),
        is_bare=data.get("bare", False),
        is_locked=data.get("locked", False),
        is_prunable=data.get("prunable", False),
    )
