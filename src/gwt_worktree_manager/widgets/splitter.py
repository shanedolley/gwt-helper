"""Draggable splitter bar for resizing adjacent panes."""

from textual import events
from textual.message import Message
from textual.widget import Widget


class SplitterBar(Widget):
    """A draggable bar for mouse-resizing adjacent panes."""

    class Resized(Message):
        """Posted during drag with the cell delta."""

        def __init__(self, splitter: "SplitterBar", delta: int) -> None:
            super().__init__()
            self.splitter = splitter
            self.delta = delta

    class ResizeComplete(Message):
        """Posted when a drag finishes."""

        def __init__(self, splitter: "SplitterBar") -> None:
            super().__init__()
            self.splitter = splitter

    DEFAULT_CSS = """
    SplitterBar {
        background: $surface-darken-1;
    }
    SplitterBar:hover {
        background: $accent 50%;
    }
    SplitterBar.-dragging {
        background: $accent;
    }
    SplitterBar.-horizontal {
        width: 1;
        height: 1fr;
    }
    SplitterBar.-vertical {
        width: 1fr;
        height: 1;
    }
    """

    can_focus = False

    def __init__(self, direction: str = "horizontal", **kwargs) -> None:
        super().__init__(**kwargs)
        self._direction = direction
        self._dragging = False
        self._last_screen_pos: int = 0
        self.add_class(f"-{direction}")

    def render(self) -> str:
        if self._direction == "horizontal":
            h = self.size.height
            if h == 0:
                return ""
            mid = h // 2
            return "\n".join("│" if i == mid else " " for i in range(h))
        else:
            w = self.size.width
            if w == 0:
                return ""
            mid = w // 2
            return "".join("─" if i == mid else " " for i in range(w))

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if self._direction == "horizontal":
            self._last_screen_pos = int(event._screen_x)
        else:
            self._last_screen_pos = int(event._screen_y)
        self._dragging = True
        self.add_class("-dragging")
        self.capture_mouse()
        event.stop()

    def _on_mouse_capture(self, event: events.MouseCapture) -> None:
        pass

    def _on_mouse_release(self, event: events.MouseRelease) -> None:
        was_dragging = self._dragging
        self._dragging = False
        self.remove_class("-dragging")
        if was_dragging:
            self.post_message(self.ResizeComplete(self))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        if self._direction == "horizontal":
            current = int(event._screen_x)
        else:
            current = int(event._screen_y)
        delta = current - self._last_screen_pos
        self._last_screen_pos = current
        if delta != 0:
            self.post_message(self.Resized(self, delta))
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._dragging:
            self.release_mouse()
        event.stop()
