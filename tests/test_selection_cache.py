"""Tests for SelectionCache."""

from gwt_worktree_manager.state.selection_cache import SelectionCache
from gwt_worktree_manager.store.metadata import WorktreeEntry


def _entry(id: str, repo: str = "myapp", branch: str = "feature/x") -> WorktreeEntry:
    return WorktreeEntry(id=id, repo_name=repo, branch=branch, path=f"/tmp/{id}")


class TestSelectionCache:
    def test_empty_cache_count_is_zero(self):
        cache = SelectionCache()
        assert cache.count == 0
        assert cache.resolved_entries() == []

    def test_toggle_marks_entry(self):
        cache = SelectionCache()
        e = _entry("id1")
        assert cache.toggle(e) is True
        assert cache.count == 1
        assert cache.contains("id1") is True

    def test_toggle_same_entry_removes_it(self):
        cache = SelectionCache()
        e = _entry("id1")
        cache.toggle(e)
        assert cache.toggle(e) is False
        assert cache.count == 0
        assert cache.contains("id1") is False

    def test_contains_unknown_id(self):
        cache = SelectionCache()
        assert cache.contains("nope") is False

    def test_resolved_entries_sorted_by_repo_then_branch(self):
        cache = SelectionCache()
        cache.toggle(_entry("a", repo="zeta", branch="z"))
        cache.toggle(_entry("b", repo="alpha", branch="m"))
        cache.toggle(_entry("c", repo="alpha", branch="a"))
        entries = cache.resolved_entries()
        assert [e.id for e in entries] == ["c", "b", "a"]

    def test_resolved_entries_returns_shallow_copy(self):
        cache = SelectionCache()
        e = _entry("id1")
        cache.toggle(e)
        entries = cache.resolved_entries()
        entries.clear()
        assert cache.count == 1

    def test_clear_succeeded_removes_only_named_ids(self):
        cache = SelectionCache()
        cache.toggle(_entry("a"))
        cache.toggle(_entry("b"))
        cache.toggle(_entry("c"))
        cache.clear_succeeded(["a", "c"])
        assert cache.count == 1
        assert cache.contains("b") is True
        assert cache.contains("a") is False
        assert cache.contains("c") is False

    def test_clear_succeeded_ignores_unknown_ids(self):
        cache = SelectionCache()
        cache.toggle(_entry("a"))
        cache.clear_succeeded(["nope"])
        assert cache.count == 1

    def test_count_reactive_callback_fires_on_mutation(self):
        cache = SelectionCache()
        observed = []
        cache.on_change(lambda n: observed.append(n))
        cache.toggle(_entry("a"))
        cache.toggle(_entry("b"))
        cache.toggle(_entry("a"))
        cache.clear_succeeded(["b"])
        assert observed == [1, 2, 1, 0]

    def test_on_change_replaces_previous_callback(self):
        cache = SelectionCache()
        a, b = [], []
        cache.on_change(a.append)
        cache.on_change(b.append)
        cache.toggle(_entry("x"))
        assert a == []
        assert b == [1]

    def test_on_change_can_be_cleared(self):
        cache = SelectionCache()
        observed = []
        cache.on_change(observed.append)
        cache.on_change(None)
        cache.toggle(_entry("x"))
        assert observed == []

    def test_observer_exception_does_not_crash_toggle(self):
        cache = SelectionCache()

        def bad_observer(_n: int) -> None:
            raise RuntimeError("boom")

        cache.on_change(bad_observer)
        # Must not raise.
        cache.toggle(_entry("x"))
        assert cache.count == 1

    def test_prune_for_repo_removes_missing_ids_only_in_that_repo(self):
        cache = SelectionCache()
        cache.toggle(_entry("keep-a", repo="alpha"))
        cache.toggle(_entry("gone-a", repo="alpha"))
        cache.toggle(_entry("keep-b", repo="beta"))
        cache.prune_for_repo("alpha", ["keep-a"])
        assert cache.contains("keep-a") is True
        assert cache.contains("gone-a") is False
        assert cache.contains("keep-b") is True  # untouched across repos

    def test_prune_for_repo_fires_on_change_only_when_removes(self):
        cache = SelectionCache()
        counts: list[int] = []
        cache.on_change(counts.append)
        cache.toggle(_entry("a", repo="alpha"))
        counts.clear()
        cache.prune_for_repo("alpha", ["a"])  # no-op
        assert counts == []
        cache.prune_for_repo("alpha", [])  # removes "a"
        assert counts == [0]
