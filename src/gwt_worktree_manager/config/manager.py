from dataclasses import dataclass, field
from pathlib import Path
import tomllib


@dataclass
class RepoConfig:
    """Per-repo configuration."""

    source_branch: str | None = None
    post_create: list[str] = field(default_factory=list)
    open_command: str = "cd"
    hook_timeout: int = 300
    hook_env: list[str] = field(default_factory=list)
    issue_url_template: str = ""


@dataclass
class IntegrationConfig:
    """Integration provider configuration."""

    enabled: bool = False
    api_key_env: str = ""
    # ADO-specific
    org_url_env: str = ""
    pat_env: str = ""


@dataclass
class Config:
    """Application configuration loaded from TOML."""

    scan_paths: list[str] = field(default_factory=lambda: ["~/Development"])
    scan_depth: int = 3
    worktrees_dir: str = "~/Development/worktrees"
    default_source_branch: str = "development"
    default_issue_tracker: str = "ado"
    default_issue_url_templates: dict[str, str] = field(
        default_factory=lambda: {
            "ado": "",
            "linear": "",
        }
    )
    cache_ttl: int = 300
    terminal: str = "terminal"
    ai_assistant: str = "none"
    editor: str = "terminal"
    editor_terminal: str = ""
    git_hosting: str = ""
    linear: IntegrationConfig = field(default_factory=IntegrationConfig)
    ado: IntegrationConfig = field(default_factory=IntegrationConfig)
    repos: dict[str, RepoConfig] = field(default_factory=dict)

    def get_repo_config(self, repo_name: str) -> RepoConfig:
        """Get config for a specific repo, falling back to defaults."""
        return self.repos.get(repo_name, RepoConfig())

    def resolve_worktrees_dir(self) -> Path:
        """Resolve ~ in worktrees_dir to actual path."""
        return Path(self.worktrees_dir).expanduser()

    def resolve_scan_paths(self) -> list[Path]:
        """Resolve ~ in scan_paths to actual paths."""
        return [Path(p).expanduser() for p in self.scan_paths]

    def get_issue_url(self, repo_name: str, tracker: str, issue_id: str) -> str:
        """Build issue URL from per-repo or global template."""
        repo_cfg = self.get_repo_config(repo_name)
        template = repo_cfg.issue_url_template or self.default_issue_url_templates.get(tracker, "")
        if not template:
            return ""
        return template.replace("{issue_id}", issue_id)


class ConfigError(Exception):
    """Raised when config file is invalid."""

    pass


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from TOML file.

    If config_path is None, uses ~/.config/gwt/config.toml.
    If the file doesn't exist, returns Config with defaults.
    """
    if config_path is None:
        from gwt_worktree_manager.platform_utils import get_config_dir
        config_path = get_config_dir() / "config.toml"

    if not config_path.exists():
        return Config()

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {config_path}: {e}") from e

    return _parse_config(data)


def _parse_config(data: dict) -> Config:
    """Parse raw TOML dict into Config dataclass."""
    general = data.get("general", {})

    defaults = Config()
    config = Config(
        scan_paths=general.get("scan_paths", ["~/Development"]),
        scan_depth=general.get("scan_depth", 3),
        worktrees_dir=general.get("worktrees_dir", "~/Development/worktrees"),
        default_source_branch=general.get("default_source_branch", "development"),
        default_issue_tracker=general.get("default_issue_tracker", "ado"),
        default_issue_url_templates={
            **defaults.default_issue_url_templates,
            **general.get("default_issue_url_templates", {}),
        },
        cache_ttl=general.get("cache_ttl", 300),
        terminal=general.get("terminal", "terminal"),
        ai_assistant=general.get("ai_assistant", "none"),
        editor=general.get("editor", "terminal"),
        editor_terminal=general.get("editor_terminal", ""),
        git_hosting=general.get("git_hosting", ""),
    )

    # Parse integrations
    integrations = data.get("integrations", {})
    if "linear" in integrations:
        lin = integrations["linear"]
        config.linear = IntegrationConfig(
            enabled=lin.get("enabled", False),
            api_key_env=lin.get("api_key_env", ""),
        )
    if "ado" in integrations:
        ado = integrations["ado"]
        config.ado = IntegrationConfig(
            enabled=ado.get("enabled", False),
            org_url_env=ado.get("org_url_env", ""),
            pat_env=ado.get("pat_env", ""),
        )

    # Parse per-repo configs
    repos = data.get("repos", {})
    for name, repo_data in repos.items():
        config.repos[name] = RepoConfig(
            source_branch=repo_data.get("source_branch"),
            post_create=repo_data.get("post_create", []),
            open_command=repo_data.get("open_command", "cd"),
            hook_timeout=repo_data.get("hook_timeout", 300),
            hook_env=repo_data.get("hook_env", []),
            issue_url_template=repo_data.get("issue_url_template", ""),
        )

    if config.scan_depth < 1:
        raise ConfigError("scan_depth must be >= 1")
    if config.cache_ttl < 0:
        raise ConfigError("cache_ttl must be >= 0")

    return config
