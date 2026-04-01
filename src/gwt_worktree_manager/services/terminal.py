"""Terminal opening strategies for different multiplexers and terminals."""

import os
import platform
import shlex
import shutil
import subprocess
import time


class TerminalOpener:
    """Opens worktrees in the configured terminal/multiplexer."""

    _ALLOWED_AI_ASSISTANTS: frozenset[str] = frozenset({"claude", "opencode", "none"})

    def __init__(self, terminal: str, ai_assistant: str = "none"):
        self._terminal = terminal
        self._ai_assistant = (
            ai_assistant if ai_assistant in self._ALLOWED_AI_ASSISTANTS else "none"
        )

    def open(self, branch: str, path: str) -> str:
        """Open a worktree. Returns a status message."""
        dispatch = {
            "cmux": self._open_cmux,
            "tmux": self._open_tmux,
        }
        opener = dispatch.get(self._terminal, self._open_specific_terminal)
        return opener(branch, path)

    # ── cmux ─────────────────────────────────────────────────────────────

    def _open_cmux(self, branch: str, path: str) -> str:
        if not shutil.which("cmux"):
            return self._open_specific_terminal(branch, path)

        # Check if workspace already exists
        result = subprocess.run(
            ["cmux", "list-workspaces"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            parts = line.strip().lstrip("* ").split(None, 1)
            if len(parts) == 2:
                ref, name = parts[0], parts[1]
                clean_name = name.split("[")[0].strip()
                if clean_name == branch:
                    self._run_silent(["cmux", "select-workspace", "--workspace", ref])
                    return f"Switched to: {branch}"

        self._create_cmux_workspace(branch, path)
        return f"Opened: {branch}"

    def _create_cmux_workspace(self, name: str, cwd: str) -> None:
        ws_out = subprocess.run(
            ["cmux", "new-workspace", "--name", name, "--cwd", cwd],
            capture_output=True, text=True,
        )
        ws_ref = self._parse_ref(ws_out.stdout, "workspace:")
        if not ws_ref:
            return

        surfaces_out = subprocess.run(
            ["cmux", "list-pane-surfaces", "--workspace", ws_ref],
            capture_output=True, text=True,
        )
        first_surface = self._parse_ref(surfaces_out.stdout, "surface:")

        # Tab 1: AI assistant (or plain terminal)
        if first_surface and self._ai_assistant != "none":
            self._run_silent(
                ["cmux", "send", "--workspace", ws_ref,
                 "--surface", first_surface, f"{self._ai_assistant}\n"],
            )

        # Tab 2: plain terminal
        self._run_silent(["cmux", "new-surface", "--workspace", ws_ref])

        # Tab 3: lazygit
        tab3_out = subprocess.run(
            ["cmux", "new-surface", "--workspace", ws_ref],
            capture_output=True, text=True,
        )
        tab3_surface = self._parse_ref(tab3_out.stdout, "surface:")
        if tab3_surface:
            time.sleep(0.3)
            self._run_silent(
                ["cmux", "send", "--workspace", ws_ref,
                 "--surface", tab3_surface, "lazygit\n"],
            )

        # Focus back to tab 1
        if first_surface:
            self._run_silent(
                ["cmux", "tab-action", "--action", "select",
                 "--tab", first_surface, "--workspace", ws_ref],
            )

    # ── tmux ─────────────────────────────────────────────────────────────

    def _open_tmux(self, branch: str, path: str) -> str:
        if not shutil.which("tmux"):
            return self._open_specific_terminal(branch, path)

        session_name = branch.replace("/", "-").replace(".", "-")

        # Check if session exists
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
        )
        if result.returncode == 0:
            switch = self._run_silent(["tmux", "switch-client", "-t", session_name])
            if switch.returncode == 0:
                return f"Switched to: {branch}"
            return (
                f"Session created: {branch} "
                f"(attach with: tmux attach -t {session_name})"
            )

        # Create new session
        self._run_silent(
            ["tmux", "new-session", "-d", "-s", session_name, "-c", path]
        )

        # Launch AI assistant in first window
        if self._ai_assistant != "none":
            self._run_silent(
                ["tmux", "send-keys", "-t", session_name, self._ai_assistant, "Enter"]
            )

        # Window 2: plain terminal
        self._run_silent(["tmux", "new-window", "-t", session_name, "-c", path])

        # Window 3: lazygit
        self._run_silent(["tmux", "new-window", "-t", session_name, "-c", path])
        self._run_silent(
            ["tmux", "send-keys", "-t", session_name, "lazygit", "Enter"]
        )

        # Focus first window and attach
        self._run_silent(["tmux", "select-window", "-t", f"{session_name}:0"])
        switch = self._run_silent(["tmux", "switch-client", "-t", session_name])
        if switch.returncode != 0:
            return (
                f"Opened: {branch} "
                f"(attach with: tmux attach -t {session_name})"
            )

        return f"Opened: {branch}"

    # ── Specific terminal dispatch ───────────────────────────────────────

    _WORKING_DIR_ARGS = {
        "gnome-terminal": lambda p: ["--working-directory", p],
        "konsole": lambda p: ["--workdir", p],
        "tilix": lambda p: ["--working-directory", p],
        "terminator": lambda p: ["--working-directory", p],
    }

    # macOS-only terminals opened via `open -a` (no CLI --working-directory flag)
    # Cross-platform terminals (alacritty, kitty, wezterm) are handled via CLI flags below
    _MACOS_APP_NAME = {
        "ghostty": "Ghostty",
        "iterm2": "iTerm",
        "warp": "Warp",
        "terminal-app": "Terminal",
    }

    def _open_specific_terminal(self, branch: str, path: str) -> str:
        """Open a worktree in the configured terminal by CLI command."""
        term = self._terminal
        os_name = platform.system()

        # macOS: open app by name
        if os_name == "Darwin" and term in self._MACOS_APP_NAME:
            app_name = self._MACOS_APP_NAME[term]
            self._run_silent(["open", "-a", app_name, path])
            return f"Opened: {branch}"

        # Windows Terminal
        if term == "wt":
            self._run_silent(["wt", "-d", path])
            return f"Opened: {branch}"

        # Terminals with --working-directory flag
        if term in self._WORKING_DIR_ARGS:
            args = self._WORKING_DIR_ARGS[term](path)
            subprocess.Popen(
                [term] + args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return f"Opened: {branch}"

        # Terminals that accept path as argument or use -e/--directory
        if term in ("alacritty", "kitty", "wezterm", "foot"):
            subprocess.Popen(
                [term, f"--working-directory={path}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return f"Opened: {branch}"

        # Fallback: OS default
        if os_name == "Darwin":
            self._run_silent(["open", "-a", "Terminal", path])
        elif os_name == "Windows":
            self._run_silent(
                ["cmd", "/c", "start", "cmd", "/k", f'cd /d "{path}"']
            )
        else:
            # Linux last resort: try xterm with shell
            if shutil.which("xterm"):
                shell = os.environ.get("SHELL", "/bin/sh")
                subprocess.Popen(
                    ["xterm", "-e", f"cd {shlex.quote(path)} && {shlex.quote(shell)}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

        return f"Opened: {branch}"

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _run_silent(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        """Run a subprocess discarding stdout/stderr. Returns the CompletedProcess."""
        return subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )

    @staticmethod
    def _parse_ref(output: str, prefix: str) -> str | None:
        for part in output.strip().split():
            if part.startswith(prefix):
                return part
        return None
