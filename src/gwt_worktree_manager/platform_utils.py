"""Platform-aware utilities for paths, clipboard, and OS detection."""

import os
import platform
from pathlib import Path


def current_os() -> str:
    """Return the current OS as 'darwin', 'windows', or 'linux'."""
    system = platform.system().lower()
    return system if system in ("darwin", "windows") else "linux"


def os_display_name(os_name: str) -> str:
    """Return a human-readable OS name."""
    return {"darwin": "macOS", "linux": "Linux", "windows": "Windows"}.get(os_name, os_name)


def get_config_dir() -> Path:
    """Return the platform-appropriate config directory for GWT."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base) / "gwt"
    # macOS and Linux both use ~/.config (XDG convention)
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / "gwt"


# ── Canonical name ↔ CLI command mappings ────────────────────────────────────
# Each dict maps: CLI command → display name
# Used by wizard (detection + display) and app (invocation).
# The CLI command is what gets stored in config.toml.

TERMINAL_MAP: dict[str, str] = {
    "cmux": "cmux",
    "tmux": "tmux",
    "zellij": "Zellij",
    "ghostty": "Ghostty",
    "alacritty": "Alacritty",
    "kitty": "Kitty",
    "wezterm": "WezTerm",
    "warp": "Warp",
    "iterm2": "iTerm2",
    "wt": "Windows Terminal",
    "gnome-terminal": "GNOME Terminal",
    "konsole": "Konsole",
    "xfce4-terminal": "XFCE Terminal",
    "tilix": "Tilix",
    "terminator": "Terminator",
    "foot": "foot",
}

# macOS app bundles that aren't on PATH — (app path, cli key)
MACOS_APP_TERMINALS: list[tuple[str, str]] = [
    ("/Applications/iTerm.app", "iterm2"),
    ("/System/Applications/Utilities/Terminal.app", "terminal-app"),
]

EDITOR_MAP: dict[str, str] = {
    "code": "VS Code",
    "cursor": "Cursor",
    "nvim": "Neovim",
    "vim": "Vim",
    "idea": "IntelliJ IDEA",
    "webstorm": "WebStorm",
    "zed": "Zed",
    "subl": "Sublime Text",
    "emacs": "Emacs",
}

AI_ASSISTANT_MAP: dict[str, str] = {
    "claude": "Claude Code",
    "opencode": "OpenCode",
}

# Reverse lookups: display name → CLI command
TERMINAL_MAP_REV: dict[str, str] = {v: k for k, v in TERMINAL_MAP.items()}
EDITOR_MAP_REV: dict[str, str] = {v: k for k, v in EDITOR_MAP.items()}
AI_ASSISTANT_MAP_REV: dict[str, str] = {v: k for k, v in AI_ASSISTANT_MAP.items()}


def get_data_dir() -> Path:
    """Return the platform-appropriate data directory for GWT."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(base) / "gwt"
    # macOS and Linux both use ~/.local/share (XDG convention)
    xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg) / "gwt"
