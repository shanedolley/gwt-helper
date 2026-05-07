"""In-memory selection cache for multi-worktree operations.

Holds a session-scoped dict of marked worktree entries keyed by ID so
downstream dialogs can render entries without re-querying the service.
"""

from __future__ import annotations

import warnings
from typing import Callable, Iterable

from gwt_worktree_manager.store.metadata import WorktreeEntry


ChangeCallback = Callable[[int], None]


class SelectionCache:
    """Session-lifetime cache of marked worktrees."""

    def __init__(self) -> None:
        self._entries: dict[str, WorktreeEntry] = {}
        self._on_change: ChangeCallback | None = None

    @property
    def count(self) -> int:
        return len(self._entries)

    def on_change(self, callback: ChangeCallback | None) -> None:
        """Register a single callback invoked with the new count on mutation.

        Exceptions raised by the callback are caught and surfaced as a
        warnings.warn so they do not abort the cache mutation. Pass None
        to clear the current callback.
        """
        self._on_change = callback

    def toggle(self, entry: WorktreeEntry) -> bool:
        """Flip membership for ``entry``. Returns True if now marked."""
        if entry.id in self._entries:
            del self._entries[entry.id]
            now_marked = False
        else:
            self._entries[entry.id] = entry
            now_marked = True
        self._notify()
        return now_marked

    def contains(self, worktree_id: str) -> bool:
        return worktree_id in self._entries

    def resolved_entries(self) -> list[WorktreeEntry]:
        """Return marked entries sorted by (repo_name, branch) as a new list."""
        return sorted(
            self._entries.values(),
            key=lambda e: (e.repo_name, e.branch),
        )

    def clear_succeeded(self, ids: Iterable[str]) -> None:
        """Remove the given IDs from the cache. Unknown IDs are ignored."""
        mutated = False
        for wid in ids:
            if wid in self._entries:
                del self._entries[wid]
                mutated = True
        if mutated:
            self._notify()

    def prune_for_repo(self, repo_name: str, valid_ids: Iterable[str]) -> None:
        """Drop cached entries for ``repo_name`` whose IDs are not in ``valid_ids``.

        Used after a repo's worktree list is refreshed to purge marks for
        worktrees that were deleted out-of-band.
        """
        valid = set(valid_ids)
        to_drop = {
            wid
            for wid, entry in self._entries.items()
            if entry.repo_name == repo_name and wid not in valid
        }
        if to_drop:
            for wid in to_drop:
                del self._entries[wid]
            self._notify()

    def _notify(self) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(self.count)
        except Exception as exc:  # noqa: BLE001 — observer must not crash the cache
            warnings.warn(f"SelectionCache observer raised: {exc!r}")
