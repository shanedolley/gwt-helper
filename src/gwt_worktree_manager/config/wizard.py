"""Interactive setup wizard for first-time GWT configuration."""

import os
import shutil
import subprocess
from pathlib import Path

import questionary
from questionary import Style
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gwt_worktree_manager.platform_utils import (
    current_os, os_display_name,
    TERMINAL_MAP, MACOS_APP_TERMINALS,
    EDITOR_MAP, AI_ASSISTANT_MAP,
)

console = Console()

# Questionary style matching the TUI aesthetic
WIZARD_STYLE = Style([
    ("qmark", "fg:ansibrightcyan bold"),
    ("question", "fg:ansiwhite bold"),
    ("answer", "fg:ansibrightcyan"),
    ("pointer", "fg:ansibrightcyan bold"),
    ("highlighted", "fg:ansibrightcyan bold"),
    ("selected", "fg:ansibrightgreen"),
    ("separator", "fg:ansibrightblack"),
    ("instruction", "fg:ansibrightblack"),
])


# ── Detection Helpers ────────────────────────────────────────────────────────


def _detect_terminals(os_name: str) -> list[tuple[str, str]]:
    """Detect installed terminals. Returns list of (cli_cmd, display_name)."""
    os_candidates = {
        "darwin": ["cmux", "tmux", "ghostty", "alacritty", "kitty", "wezterm", "warp"],
        "linux": ["cmux", "tmux", "ghostty", "alacritty", "kitty", "wezterm",
                   "gnome-terminal", "konsole", "xfce4-terminal", "tilix", "terminator", "foot"],
        "windows": ["wt", "alacritty", "wezterm", "ghostty"],
    }
    found = []
    for cmd in os_candidates.get(os_name, []):
        if shutil.which(cmd):
            found.append((cmd, TERMINAL_MAP.get(cmd, cmd)))

    if os_name == "darwin":
        for app_path, cli_key in MACOS_APP_TERMINALS:
            if Path(app_path).exists() and not any(c == cli_key for c, _ in found):
                found.append((cli_key, TERMINAL_MAP.get(cli_key, cli_key)))

    return found


def _detect_ai_tools() -> list[tuple[str, str]]:
    """Detect installed AI assistants. Returns list of (cli_cmd, display_name)."""
    found = []
    for cmd, name in AI_ASSISTANT_MAP.items():
        if shutil.which(cmd):
            found.append((cmd, name))
    return found


def _detect_editors() -> list[tuple[str, str]]:
    """Detect installed editors. Returns list of (cli_cmd, display_name)."""
    found = []
    for cmd, name in EDITOR_MAP.items():
        if shutil.which(cmd):
            found.append((cmd, name))
    return found


def _scan_repos(scan_path: str) -> list[Path]:
    """Scan for git repos under the given path."""
    root = Path(scan_path).expanduser().resolve()
    repos = []
    if not root.exists():
        return repos

    for dirpath, dirnames, _ in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth > 5:
            dirnames.clear()
            continue
        if ".git" in dirnames:
            repos.append(Path(dirpath))
            dirnames.clear()  # Don't descend into repo subdirs
        # Skip common non-repo dirs for speed
        dirnames[:] = [
            d for d in dirnames
            if d not in {"node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"}
        ]
    return sorted(repos)


def _detect_default_branch(repos: list[Path]) -> str:
    """Detect the default branch from the first repo found."""
    for repo in repos[:3]:
        for branch in ["main", "master", "development"]:
            try:
                result = subprocess.run(
                    ["git", "branch", "--list", branch],
                    capture_output=True, text=True, cwd=repo, timeout=10,
                )
                if result.stdout.strip():
                    return branch
                # Check remote
                result = subprocess.run(
                    ["git", "branch", "-r", "--list", f"origin/{branch}"],
                    capture_output=True, text=True, cwd=repo, timeout=10,
                )
                if result.stdout.strip():
                    return branch
            except subprocess.TimeoutExpired:
                continue
    return "main"


def _check_git() -> tuple[bool, str]:
    git_path = shutil.which("git")
    if not git_path:
        return False, "not found"
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True)
        return True, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def _check_cli(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _check_gh_auth() -> bool:
    try:
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_az_auth() -> bool:
    try:
        result = subprocess.run(
            ["az", "account", "show"], capture_output=True, text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


# ── Installation Helpers ─────────────────────────────────────────────────────


def _install_cli(name: str, cmd: str, os_name: str) -> bool:
    """Offer to install a CLI tool. Returns True if installed."""
    install_cmds = {
        "gh": {
            "darwin": ["brew", "install", "gh"],
            "linux": None,  # varies
            "windows": ["winget", "install", "--id", "GitHub.cli"],
        },
        "az": {
            "darwin": ["brew", "install", "azure-cli"],
            "linux": None,
            "windows": ["winget", "install", "--id", "Microsoft.AzureCLI"],
        },
    }

    # Linux needs special handling
    if os_name == "linux" and cmd in install_cmds:
        if shutil.which("apt"):
            install_cmds[cmd]["linux"] = ["sudo", "apt", "install", "-y", cmd]
        elif shutil.which("dnf"):
            install_cmds[cmd]["linux"] = ["sudo", "dnf", "install", "-y", cmd]
        elif shutil.which("pacman"):
            install_cmds[cmd]["linux"] = ["sudo", "pacman", "-S", "--noconfirm", cmd]
        elif shutil.which("brew"):
            install_cmds[cmd]["linux"] = ["brew", "install", cmd]

    install_cmd = install_cmds.get(cmd, {}).get(os_name)
    if install_cmd is None:
        console.print(f"  [yellow]Please install {name} manually and re-run setup.[/]")
        return False

    console.print(f"  Install command: [cyan]{' '.join(install_cmd)}[/]")
    if questionary.confirm(
        f"  Install {name} now?", default=True, style=WIZARD_STYLE,
    ).ask():
        try:
            result = subprocess.run(install_cmd, timeout=300)
        except subprocess.TimeoutExpired:
            console.print(f"  [red]Installation timed out. Please install {name} manually.[/]")
            return False
        if result.returncode == 0:
            console.print(f"  [green]{name} installed successfully.[/]")
            return True
        else:
            console.print("  [red]Installation failed. Please install manually.[/]")
            return False
    return False


def _authenticate_cli(name: str, auth_cmd: list[str], check_fn) -> bool:
    """Walk user through CLI authentication."""
    if check_fn():
        console.print(f"  [green]{name}: authenticated[/]")
        return True

    console.print(f"  [yellow]{name}: not authenticated[/]")
    if questionary.confirm(
        f"  Authenticate with {name} now?", default=True, style=WIZARD_STYLE,
    ).ask():
        subprocess.run(auth_cmd)
        if check_fn():
            console.print(f"  [green]{name}: authenticated successfully[/]")
            return True
        else:
            console.print(f"  [red]{name}: authentication failed. You can retry later.[/]")
    return False


# ── Wizard Sections ──────────────────────────────────────────────────────────


def _section(title: str, subtitle: str = "") -> None:
    text = Text(title, style="bold cyan")
    if subtitle:
        text.append(f"\n{subtitle}", style="bright_black")
    console.print(Panel(text, border_style="cyan", padding=(0, 1)))


def _select_with_default(
    prompt: str,
    items: list[tuple[str, str]],
) -> tuple[list[str], str]:
    """Checkbox select from (cli_cmd, display_name) pairs.

    Shows display names to user, returns CLI commands.
    Returns (selected_cmds, default_cmd).
    """
    display_names = [name for _, name in items]
    cmd_by_name = {name: cmd for cmd, name in items}

    selected_names = questionary.checkbox(
        prompt,
        choices=display_names,
        style=WIZARD_STYLE,
        instruction="(space to select, enter to confirm)",
    ).ask()

    if selected_names is None:
        raise SystemExit("Setup cancelled.")

    if not selected_names:
        return [], ""

    selected_cmds = [cmd_by_name[n] for n in selected_names]

    if len(selected_cmds) == 1:
        return selected_cmds, selected_cmds[0]

    default_name = questionary.select(
        "  Which should be the default?",
        choices=selected_names,
        style=WIZARD_STYLE,
    ).ask()

    if default_name is None:
        raise SystemExit("Setup cancelled.")

    return selected_cmds, cmd_by_name[default_name]


# ── Main Wizard ──────────────────────────────────────────────────────────────


def run_wizard() -> dict:
    """Run the interactive setup wizard. Returns config dict."""
    os_name = current_os()
    config = {"os": os_name}

    console.print()
    console.print(Panel(
        "[bold white]GWT Worktree Manager[/] [bright_black]— Setup Wizard[/]\n"
        f"[bright_black]Detected OS: {os_display_name(os_name)}[/]",
        border_style="cyan",
        padding=(1, 2),
    ))

    # ── 1. Git ───────────────────────────────────────────────────────────
    _section("Git", "Checking git installation")

    git_ok, git_info = _check_git()
    if not git_ok:
        console.print("  [red]Git not found. Please install git and re-run.[/]")
        raise SystemExit(1)
    console.print(f"  [green]{git_info}[/]")

    # gh CLI — detect/install and record git hosting
    gh_available = _check_cli("gh")
    if gh_available:
        console.print("  [green]gh CLI: installed[/]")
        _authenticate_cli("GitHub CLI", ["gh", "auth", "login"], _check_gh_auth)
    else:
        console.print("  [yellow]gh CLI: not installed[/]")
        if _install_cli("GitHub CLI", "gh", os_name):
            _authenticate_cli("GitHub CLI", ["gh", "auth", "login"], _check_gh_auth)
            gh_available = True
    config["git_hosting"] = "github" if gh_available else ""

    # ── 2. Directories ───────────────────────────────────────────────────
    _section("Directories", "Where are your git repos?")

    if os_name == "windows":
        default_scan = str(Path.home() / "Documents" / "Projects")
    else:
        default_scan = str(Path.home() / "Development")

    scan_path = questionary.text(
        "  Scan path:",
        default=default_scan,
        style=WIZARD_STYLE,
    ).ask()
    if scan_path is None:
        raise SystemExit("Setup cancelled.")
    config["scan_paths"] = [scan_path]

    console.print("  [bright_black]Scanning for git repos...[/]")
    repos = _scan_repos(scan_path)
    console.print(f"  [green]Found {len(repos)} repositories[/]")

    default_wt = str(Path(scan_path).expanduser() / "worktrees")
    worktrees_dir = questionary.text(
        "  Worktrees directory:",
        default=default_wt,
        style=WIZARD_STYLE,
    ).ask()
    if worktrees_dir is None:
        raise SystemExit("Setup cancelled.")
    config["worktrees_dir"] = worktrees_dir

    # ── 3. Default branch (auto-detect) ──────────────────────────────────
    default_branch = _detect_default_branch(repos)
    config["default_source_branch"] = default_branch
    console.print(f"  [bright_black]Default source branch: {default_branch}[/]")

    # ── 4. Terminal & Multiplexer ────────────────────────────────────────
    _section("Terminal", "How should GWT open worktrees?")

    detected_terminals = _detect_terminals(os_name)
    seen_cmds = set()
    unique_terminals = []
    for cmd, name in detected_terminals:
        if cmd not in seen_cmds:
            seen_cmds.add(cmd)
            unique_terminals.append((cmd, name))

    if unique_terminals:
        selected_terms, default_term = _select_with_default(
            "  Select terminal(s):", unique_terminals,
        )
        config["terminals"] = selected_terms
        config["terminal"] = default_term or "terminal"
    else:
        console.print("  [yellow]No known terminals detected.[/]")
        config["terminals"] = []
        config["terminal"] = "terminal"

    # ── 5. AI Coding Assistant ───────────────────────────────────────────
    _section("AI Assistant", "Which AI coding assistant(s) do you use?")

    detected_ai = _detect_ai_tools()

    if detected_ai:
        selected_ai, default_ai = _select_with_default(
            "  Select AI assistant(s):", detected_ai,
        )
        config["ai_assistant"] = default_ai or "none"
    else:
        console.print("  [bright_black]No AI assistants detected.[/]")
        config["ai_assistant"] = "none"

    # ── 6. Project Management ────────────────────────────────────────────
    _section("Project Management", "Which issue tracker(s) do you use?")

    pm_items = [("ado", "Azure DevOps"), ("linear", "Linear")]
    selected_pm, default_pm = _select_with_default(
        "  Select tracker(s):", pm_items,
    )
    config["project_management"] = selected_pm
    config["default_issue_tracker"] = default_pm or ""

    # ADO: check Azure CLI
    if "ado" in selected_pm:
        console.print()
        if _check_cli("az"):
            console.print("  [green]Azure CLI: installed[/]")
            _authenticate_cli("Azure CLI", ["az", "login"], _check_az_auth)
        else:
            console.print("  [yellow]Azure CLI: not installed[/]")
            if _install_cli("Azure CLI", "az", os_name):
                _authenticate_cli("Azure CLI", ["az", "login"], _check_az_auth)

    # ── 7. Editor ────────────────────────────────────────────────────────
    _section("Editor", "How should worktrees be opened for editing?")

    detected_editors = _detect_editors()
    # Build choices: display names for detected editors + "Open in terminal"
    editor_cmd_by_name = {name: cmd for cmd, name in detected_editors}
    editor_display_names = [name for _, name in detected_editors] + ["Open in terminal"]

    editor_name = questionary.select(
        "  Select editor:",
        choices=editor_display_names,
        style=WIZARD_STYLE,
    ).ask()
    if editor_name is None:
        raise SystemExit("Setup cancelled.")

    if editor_name == "Open in terminal":
        config["editor"] = "terminal"
        # Let user pick which terminal for editing
        term_choices = config.get("terminals", [])
        if term_choices:
            term_names = [(cmd, TERMINAL_MAP.get(cmd, cmd)) for cmd in term_choices]
            term_display = [name for _, name in term_names]
            term_cmd_by_name = {name: cmd for cmd, name in term_names}
            picked = questionary.select(
                "  Which terminal?",
                choices=term_display,
                style=WIZARD_STYLE,
            ).ask()
            if picked is None:
                raise SystemExit("Setup cancelled.")
            config["editor_terminal"] = term_cmd_by_name[picked]
        else:
            config["editor_terminal"] = config.get("terminal", "terminal")
    else:
        config["editor"] = editor_cmd_by_name[editor_name]

    return config


def _toml_str(value: str) -> str:
    """Return a TOML basic string (double-quoted, backslashes escaped)."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_config(config: dict) -> Path:
    """Write the wizard results to config.toml."""
    from gwt_worktree_manager.platform_utils import get_config_dir
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"

    lines = ["[general]"]
    lines.append(f'scan_paths = [{", ".join(_toml_str(p) for p in config["scan_paths"])}]')
    lines.append(f'worktrees_dir = {_toml_str(config["worktrees_dir"])}')
    lines.append(f'default_source_branch = "{config["default_source_branch"]}"')

    if config.get("default_issue_tracker"):
        lines.append(f'default_issue_tracker = "{config["default_issue_tracker"]}"')

    lines.append(f'terminal = "{config.get("terminal", "terminal")}"')
    lines.append(f'ai_assistant = "{config.get("ai_assistant", "none")}"')
    lines.append(f'editor = "{config.get("editor", "terminal")}"')

    if config.get("git_hosting"):
        lines.append(f'git_hosting = "{config["git_hosting"]}"')

    if config.get("editor_terminal"):
        lines.append(f'editor_terminal = "{config["editor_terminal"]}"')

    lines.append("")

    pm = config.get("project_management", [])
    if "linear" in pm:
        lines.append("[integrations.linear]")
        lines.append("enabled = true")
        lines.append('api_key_env = "LINEAR_API_KEY"')
        lines.append("")

    if "ado" in pm:
        lines.append("[integrations.ado]")
        lines.append("enabled = true")
        lines.append('org_url_env = "ADO_ORG_URL"')
        lines.append('pat_env = "ADO_PAT"')
        lines.append("")

    config_path.write_text("\n".join(lines) + "\n")
    return config_path


def print_summary(config: dict, config_path: Path) -> None:
    """Print a summary of the configuration."""
    console.print()

    table = Table(
        title="Configuration Summary",
        border_style="cyan",
        show_header=False,
        padding=(0, 2),
    )
    table.add_column("Setting", style="bright_black")
    table.add_column("Value", style="cyan")

    table.add_row("Config file", str(config_path))
    table.add_row("Scan paths", ", ".join(config["scan_paths"]))
    table.add_row("Worktrees dir", config["worktrees_dir"])
    table.add_row("Source branch", config["default_source_branch"])
    table.add_row("Terminal", config.get("terminal", "terminal"))

    ai = config.get("ai_assistant", "none")
    table.add_row("AI assistant", ai)

    pm = config.get("project_management", [])
    table.add_row("Issue trackers", ", ".join(pm) if pm else "none")
    table.add_row("Editor", config.get("editor", "terminal"))

    console.print(table)
    console.print()
    console.print("[bright_black]Run [cyan]gwt[/cyan] to launch the TUI, or [cyan]gwt setup[/cyan] to reconfigure.[/]")
    console.print()
