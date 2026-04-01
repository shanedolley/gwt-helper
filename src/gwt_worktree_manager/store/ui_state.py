"""Persistent UI state for pane sizes and layout preferences."""

from pathlib import Path
import json
import os

_MIN_LEFT_WIDTH = 15
_MAX_LEFT_WIDTH = 80
_MIN_DETAIL_HEIGHT = 3
_MAX_DETAIL_HEIGHT = 30

_DEFAULT_LEFT_WIDTH = 30
_DEFAULT_DETAIL_HEIGHT = 8


class UIStateStore:
    """Persists UI layout state to JSON."""

    def __init__(self, state_path: Path | None = None):
        self._path = state_path or (
            Path.home() / ".local" / "share" / "gwt" / "ui_state.json"
        )
        self._state: dict = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._state = {}
            return
        try:
            with open(self._path) as f:
                self._state = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._state = {}

    def save(self) -> None:
        """Atomically save state to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        fd = os.open(str(temp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            try:
                os.unlink(str(temp_path))
            except OSError:
                pass
            raise
        os.rename(str(temp_path), str(self._path))

    @property
    def left_panel_width(self) -> int:
        return self._state.get("left_panel_width", _DEFAULT_LEFT_WIDTH)

    @left_panel_width.setter
    def left_panel_width(self, value: int) -> None:
        self._state["left_panel_width"] = max(
            _MIN_LEFT_WIDTH, min(_MAX_LEFT_WIDTH, value)
        )

    @property
    def detail_panel_height(self) -> int:
        return self._state.get("detail_panel_height", _DEFAULT_DETAIL_HEIGHT)

    @detail_panel_height.setter
    def detail_panel_height(self, value: int) -> None:
        self._state["detail_panel_height"] = max(
            _MIN_DETAIL_HEIGHT, min(_MAX_DETAIL_HEIGHT, value)
        )
