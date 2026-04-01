from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
import asyncio
import os
import signal
import time

from gwt_worktree_manager.config.manager import Config


@dataclass
class HookResult:
    """Result of a single hook execution."""

    success: bool
    command: str
    exit_code: int | None
    output: str
    duration_seconds: float
    timed_out: bool = False


@dataclass
class HooksResult:
    """Result of running all hooks for a worktree."""

    results: list[HookResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def failures(self) -> list[HookResult]:
        return [r for r in self.results if not r.success]


def detect_package_manager(worktree_path: Path) -> str | None:
    """Detect package manager from lock files.

    Returns the install command string, or None if no lock file found.
    Detection order: pnpm > yarn > npm > bun > pip
    """
    checks = [
        ("pnpm-lock.yaml", "pnpm install"),
        ("yarn.lock", "yarn install"),
        ("package-lock.json", "npm install"),
        ("bun.lockb", "bun install"),
        ("bun.lock", "bun install"),
        ("requirements.txt", "pip install -r requirements.txt"),
        ("pyproject.toml", "pip install -e ."),
    ]

    for filename, command in checks:
        if (worktree_path / filename).exists():
            return command

    return None


class HookRunner:
    """Executes configurable post-create hooks with security controls."""

    # Environment variables allowed in hook subprocesses (allowlist, not denylist)
    ALLOWED_ENV_VARS = frozenset({
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "EDITOR",
        "VISUAL",
    })

    def __init__(self, config: Config):
        self._config = config

    async def run_post_create_hooks(
        self,
        repo_name: str,
        worktree_path: Path,
        on_output: Callable[[str, str], None] | None = None,
    ) -> HooksResult:
        """Run all post-create hooks for a repo.

        Hooks run sequentially. If one fails, subsequent hooks still execute.

        Args:
            repo_name: Name of the repo (for config lookup)
            worktree_path: Path to the new worktree (hooks run here)
            on_output: Optional callback(command, line) for streaming output

        Returns:
            HooksResult with all individual results
        """
        repo_config = self._config.get_repo_config(repo_name)
        hooks = repo_config.post_create

        if not hooks:
            # Try auto-detection
            detected = detect_package_manager(worktree_path)
            if detected:
                hooks = [detected]

        result = HooksResult()
        for cmd in hooks:
            hook_result = await self._run_single_hook(
                cmd=cmd,
                cwd=worktree_path,
                timeout=repo_config.hook_timeout,
                extra_env=repo_config.hook_env,
                on_output=on_output,
            )
            result.results.append(hook_result)

        return result

    async def _run_single_hook(
        self,
        cmd: str,
        cwd: Path,
        timeout: int,
        extra_env: list[str] | None = None,
        on_output: Callable[[str, str], None] | None = None,
    ) -> HookResult:
        """Execute a single hook command.

        Uses shell=True (via create_subprocess_shell) since hook commands
        are free-form strings from config (e.g., "pnpm install && cp .env.example .env").

        Security:
        - Runs in its own process group (start_new_session=True)
        - Environment is an allowlist, not the full parent environment
        - Timeout enforced with process group kill on expiry
        """
        env = self._build_env(extra_env)
        start_time = time.monotonic()
        output_lines: list[str] = []

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
                cwd=cwd,
                env=env,
                start_new_session=True,
            )

            try:
                # Read output with timeout
                await asyncio.wait_for(
                    self._read_output(proc, cmd, on_output, output_lines),
                    timeout=timeout,
                )
                await proc.wait()
            except asyncio.TimeoutError:
                # Kill the process group
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass

                duration = time.monotonic() - start_time
                return HookResult(
                    success=False,
                    command=cmd,
                    exit_code=None,
                    output="\n".join(output_lines),
                    duration_seconds=duration,
                    timed_out=True,
                )

            duration = time.monotonic() - start_time
            return HookResult(
                success=proc.returncode == 0,
                command=cmd,
                exit_code=proc.returncode,
                output="\n".join(output_lines),
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.monotonic() - start_time
            return HookResult(
                success=False,
                command=cmd,
                exit_code=None,
                output=str(e),
                duration_seconds=duration,
            )

    async def _read_output(
        self,
        proc: asyncio.subprocess.Process,
        cmd: str,
        on_output: Callable[[str, str], None] | None,
        output_lines: list[str],
    ) -> None:
        """Read process output line by line, calling callback if provided."""
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode().rstrip("\n")
            output_lines.append(decoded)
            if on_output:
                on_output(cmd, decoded)

    def _build_env(self, extra_env: list[str] | None = None) -> dict[str, str]:
        """Build a sanitized environment from allowlist.

        Starts with an empty dict, copies only allowed variables
        from the current environment, then adds any extra variables
        specified in the repo config's hook_env array.
        """
        env: dict[str, str] = {}

        # Copy allowed vars from current environment
        for var in self.ALLOWED_ENV_VARS:
            value = os.environ.get(var)
            if value is not None:
                env[var] = value

        # Add extra vars from config
        if extra_env:
            for var in extra_env:
                value = os.environ.get(var)
                if value is not None:
                    env[var] = value

        return env
