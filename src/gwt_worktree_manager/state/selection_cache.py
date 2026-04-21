"""In-memory selection cache for multi-worktree operations.

Holds a session-scoped set of marked worktree IDs plus a resolver map from
ID to ``WorktreeEntry`` so downstream dialogs can render entries without
re-querying the service.
"""

from __future__ import annotations

from typing import Callable

from gwt_worktree_manager.store.metadata import WorktreeEntry


ChangeCallback = Callable[[int], None]


class SelectionCache:
    """Session-lifetime cache of marked worktrees."""

    def __init__(self) -> None:
        self._ids: set[str] = set()
        self._entries: dict[str, WorktreeEntry] = {}
        self._observers: list[ChangeCallback] = []

    @property
    def count(self) -> int:
        return len(self._ids)

    def on_change(self, callback: ChangeCallback) -> None:
        """Register a callback invoked with the new count on every mutation."""
        self._observers.append(callback)

    def toggle(self, entry: WorktreeEntry) -> bool:
        """Flip membership for ``entry``. Returns True if now marked."""
        if entry.id in self._ids:
            self._ids.discard(entry.id)
            self._entries.pop(entry.id, None)
            now_marked = False
        else:
            self._ids.add(entry.id)
            self._entries[entry.id] = entry
            now_marked = True
        self._notify()
        return now_marked

    def contains(self, worktree_id: str) -> bool:
        return worktree_id in self._ids

    def resolved_entries(self) -> list[WorktreeEntry]:
        """Return marked entries sorted by (repo_name, branch) as a new list."""
        return sorted(
            self._entries.values(),
            key=lambda e: (e.repo_name, e.branch),
        )

    def clear_succeeded(self, ids: list[str]) -> None:
        """Remove the given IDs from the cache. Unknown IDs are ignored."""
        mutated = False
        for wid in ids:
            if wid in self._ids:
                self._ids.discard(wid)
                self._entries.pop(wid, None)
                mutated = True
        if mutated:
            self._notify()

    def _notify(self) -> None:
        for obs in self._observers:
            obs(self.count)
