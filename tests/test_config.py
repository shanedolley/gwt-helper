import pytest
from gwt_worktree_manager.config.manager import load_config, Config, ConfigError


class TestLoadConfig:
    def test_missing_config_file_returns_defaults(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.toml")
        assert config.scan_paths == ["~/Development"]
        assert config.scan_depth == 3
        assert config.worktrees_dir == "~/Development/worktrees"
        assert config.default_source_branch == "development"
        assert config.cache_ttl == 300

    def test_empty_config_file_returns_defaults(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        config = load_config(config_file)
        assert config.scan_depth == 3

    def test_invalid_toml_raises_config_error(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("this is not [valid toml")
        with pytest.raises(ConfigError, match="Invalid TOML"):
            load_config(config_file)

    def test_partial_config_merges_with_defaults(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('[general]\nscan_depth = 5\n')
        config = load_config(config_file)
        assert config.scan_depth == 5
        assert config.worktrees_dir == "~/Development/worktrees"  # default preserved

    def test_full_config_parses_all_sections(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('''
[general]
scan_paths = ["~/Projects"]
scan_depth = 4
worktrees_dir = "~/worktrees"
default_source_branch = "main"
cache_ttl = 600

[integrations.linear]
api_key_env = "LINEAR_API_KEY"
enabled = true

[integrations.ado]
org_url_env = "ADO_ORG_URL"
pat_env = "ADO_PAT"
enabled = false

[repos.myapp]
source_branch = "main"
post_create = ["pnpm install", "cp .env.example .env"]
open_command = "code ."
hook_timeout = 120
hook_env = ["NODE_ENV"]
''')
        config = load_config(config_file)
        assert config.scan_paths == ["~/Projects"]
        assert config.scan_depth == 4
        assert config.worktrees_dir == "~/worktrees"
        assert config.default_source_branch == "main"
        assert config.cache_ttl == 600
        assert config.linear.enabled is True
        assert config.linear.api_key_env == "LINEAR_API_KEY"
        assert config.ado.enabled is False
        assert config.ado.pat_env == "ADO_PAT"
        repo = config.get_repo_config("myapp")
        assert repo.source_branch == "main"
        assert repo.post_create == ["pnpm install", "cp .env.example .env"]
        assert repo.open_command == "code ."
        assert repo.hook_timeout == 120
        assert repo.hook_env == ["NODE_ENV"]

    def test_unknown_keys_ignored(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('[general]\nunknown_key = "value"\nscan_depth = 2\n')
        config = load_config(config_file)
        assert config.scan_depth == 2

    def test_get_repo_config_returns_default_for_unknown_repo(self):
        config = Config()
        repo = config.get_repo_config("unknown-repo")
        assert repo.open_command == "cd"
        assert repo.post_create == []
        assert repo.hook_timeout == 300

    def test_resolve_worktrees_dir_expands_tilde(self):
        config = Config(worktrees_dir="~/Development/worktrees")
        resolved = config.resolve_worktrees_dir()
        assert "~" not in str(resolved)
        assert resolved.is_absolute()

    def test_resolve_scan_paths_expands_tilde(self):
        config = Config(scan_paths=["~/Development", "~/Projects"])
        resolved = config.resolve_scan_paths()
        assert len(resolved) == 2
        for p in resolved:
            assert "~" not in str(p)
            assert p.is_absolute()

    def test_hook_timeout_default(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('[repos.myapp]\npost_create = ["echo hello"]\n')
        config = load_config(config_file)
        assert config.get_repo_config("myapp").hook_timeout == 300

    def test_cache_ttl_default(self):
        config = Config()
        assert config.cache_ttl == 300
