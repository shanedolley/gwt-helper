import pytest
import os
from gwt_worktree_manager.services.hooks import (
    HookRunner,
    HookResult,
    HooksResult,
    detect_package_manager,
)
from gwt_worktree_manager.config.manager import Config, RepoConfig


class TestHookRunner:
    @pytest.fixture
    def runner(self):
        config = Config()
        return HookRunner(config)

    @pytest.fixture
    def hook_dir(self, tmp_path):
        """A temp directory to use as worktree_path for hooks."""
        return tmp_path

    @pytest.mark.asyncio
    async def test_runs_simple_command(self, runner, hook_dir):
        result = await runner._run_single_hook(
            cmd="echo hello",
            cwd=hook_dir,
            timeout=10,
        )
        assert result.success is True
        assert result.exit_code == 0
        assert "hello" in result.output
        assert result.duration_seconds > 0
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_captures_failure(self, runner, hook_dir):
        result = await runner._run_single_hook(
            cmd="exit 1",
            cwd=hook_dir,
            timeout=10,
        )
        assert result.success is False
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self, runner, hook_dir):
        result = await runner._run_single_hook(
            cmd="sleep 60",
            cwd=hook_dir,
            timeout=1,  # 1 second timeout
        )
        assert result.success is False
        assert result.timed_out is True
        assert result.duration_seconds < 10  # Should be killed quickly

    @pytest.mark.asyncio
    async def test_environment_allowlist(self, runner, hook_dir):
        # Set a sensitive var that should NOT be in hook env
        os.environ["LINEAR_API_KEY"] = "secret-key"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "aws-secret"
        try:
            result = await runner._run_single_hook(
                cmd="env",
                cwd=hook_dir,
                timeout=10,
            )
            assert "LINEAR_API_KEY" not in result.output
            assert "AWS_SECRET_ACCESS_KEY" not in result.output
            # PATH should be present
            assert "PATH=" in result.output
        finally:
            del os.environ["LINEAR_API_KEY"]
            del os.environ["AWS_SECRET_ACCESS_KEY"]

    @pytest.mark.asyncio
    async def test_extra_env_vars_from_config(self, runner, hook_dir):
        os.environ["NODE_ENV"] = "development"
        try:
            result = await runner._run_single_hook(
                cmd="env",
                cwd=hook_dir,
                timeout=10,
                extra_env=["NODE_ENV"],
            )
            assert "NODE_ENV=development" in result.output
        finally:
            del os.environ["NODE_ENV"]

    @pytest.mark.asyncio
    async def test_output_callback(self, runner, hook_dir):
        lines = []

        def callback(cmd, line):
            lines.append((cmd, line))

        await runner._run_single_hook(
            cmd='echo "line1" && echo "line2"',
            cwd=hook_dir,
            timeout=10,
            on_output=callback,
        )
        assert len(lines) == 2
        assert lines[0][1] == "line1"
        assert lines[1][1] == "line2"

    @pytest.mark.asyncio
    async def test_runs_in_correct_directory(self, runner, hook_dir):
        result = await runner._run_single_hook(
            cmd="pwd",
            cwd=hook_dir,
            timeout=10,
        )
        assert result.success
        # The output path should match hook_dir (resolved)
        assert str(hook_dir.resolve()) in result.output or str(hook_dir) in result.output


class TestRunPostCreateHooks:
    @pytest.mark.asyncio
    async def test_runs_configured_hooks_in_order(self, tmp_path):
        config = Config()
        config.repos["test-repo"] = RepoConfig(
            post_create=["echo first", "echo second"],
        )
        runner = HookRunner(config)
        result = await runner.run_post_create_hooks("test-repo", tmp_path)
        assert len(result.results) == 2
        assert result.results[0].output == "first"
        assert result.results[1].output == "second"
        assert result.all_succeeded

    @pytest.mark.asyncio
    async def test_continue_on_failure(self, tmp_path):
        config = Config()
        config.repos["test-repo"] = RepoConfig(
            post_create=["exit 1", "echo survived"],
        )
        runner = HookRunner(config)
        result = await runner.run_post_create_hooks("test-repo", tmp_path)
        assert len(result.results) == 2
        assert result.results[0].success is False
        assert result.results[1].success is True
        assert result.results[1].output == "survived"
        assert not result.all_succeeded
        assert len(result.failures) == 1

    @pytest.mark.asyncio
    async def test_no_hooks_configured_no_lockfile(self, tmp_path):
        config = Config()
        runner = HookRunner(config)
        result = await runner.run_post_create_hooks("unknown-repo", tmp_path)
        assert len(result.results) == 0

    @pytest.mark.asyncio
    async def test_auto_detects_package_manager(self, tmp_path):
        # Create a lock file
        (tmp_path / "package-lock.json").write_text("{}")
        config = Config()
        runner = HookRunner(config)
        result = await runner.run_post_create_hooks("unknown-repo", tmp_path)
        assert len(result.results) == 1
        assert "npm install" in result.results[0].command


class TestDetectPackageManager:
    def test_pnpm(self, tmp_path):
        (tmp_path / "pnpm-lock.yaml").write_text("")
        assert detect_package_manager(tmp_path) == "pnpm install"

    def test_yarn(self, tmp_path):
        (tmp_path / "yarn.lock").write_text("")
        assert detect_package_manager(tmp_path) == "yarn install"

    def test_npm(self, tmp_path):
        (tmp_path / "package-lock.json").write_text("{}")
        assert detect_package_manager(tmp_path) == "npm install"

    def test_bun(self, tmp_path):
        (tmp_path / "bun.lockb").write_bytes(b"")
        assert detect_package_manager(tmp_path) == "bun install"

    def test_pip_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask")
        assert detect_package_manager(tmp_path) == "pip install -r requirements.txt"

    def test_pip_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'")
        assert detect_package_manager(tmp_path) == "pip install -e ."

    def test_pnpm_takes_precedence(self, tmp_path):
        (tmp_path / "pnpm-lock.yaml").write_text("")
        (tmp_path / "package-lock.json").write_text("{}")
        assert detect_package_manager(tmp_path) == "pnpm install"

    def test_no_lockfile(self, tmp_path):
        assert detect_package_manager(tmp_path) is None


class TestHooksResult:
    def test_all_succeeded_true(self):
        r = HooksResult(results=[
            HookResult(success=True, command="a", exit_code=0, output="", duration_seconds=0.1),
            HookResult(success=True, command="b", exit_code=0, output="", duration_seconds=0.1),
        ])
        assert r.all_succeeded is True
        assert r.failures == []

    def test_all_succeeded_false(self):
        r = HooksResult(results=[
            HookResult(success=True, command="a", exit_code=0, output="", duration_seconds=0.1),
            HookResult(success=False, command="b", exit_code=1, output="err", duration_seconds=0.1),
        ])
        assert r.all_succeeded is False
        assert len(r.failures) == 1

    def test_empty_results(self):
        r = HooksResult()
        assert r.all_succeeded is True
        assert r.failures == []


class TestBuildEnv:
    def test_includes_path(self):
        runner = HookRunner(Config())
        env = runner._build_env()
        assert "PATH" in env

    def test_excludes_sensitive_vars(self):
        os.environ["GITHUB_TOKEN"] = "ghp_secret"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-secret"
        try:
            runner = HookRunner(Config())
            env = runner._build_env()
            assert "GITHUB_TOKEN" not in env
            assert "ANTHROPIC_API_KEY" not in env
        finally:
            del os.environ["GITHUB_TOKEN"]
            del os.environ["ANTHROPIC_API_KEY"]

    def test_includes_allowed_vars(self):
        runner = HookRunner(Config())
        env = runner._build_env()
        # These should be present if they're in the current env
        for var in ["PATH", "HOME", "USER"]:
            if var in os.environ:
                assert var in env

    def test_extra_env_added(self):
        os.environ["CUSTOM_VAR"] = "custom_value"
        try:
            runner = HookRunner(Config())
            env = runner._build_env(extra_env=["CUSTOM_VAR"])
            assert env.get("CUSTOM_VAR") == "custom_value"
        finally:
            del os.environ["CUSTOM_VAR"]

    def test_extra_env_missing_var_skipped(self):
        runner = HookRunner(Config())
        env = runner._build_env(extra_env=["NONEXISTENT_VAR_XYZ"])
        assert "NONEXISTENT_VAR_XYZ" not in env
