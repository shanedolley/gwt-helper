"""Tests for WorktreeService.delete_worktrees_bulk."""

import pytest

from gwt_worktree_manager.services.worktree import (
    BulkDeleteResult,
    UncommittedChangesError,
    WorktreeNotFoundError,
    WorktreeService,
)
from gwt_worktree_manager.store.metadata import WorktreeEntry


def _entry(id: str) -> WorktreeEntry:
    return WorktreeEntry(
        id=id,
        repo_name="myapp",
        branch=f"feature/{id}",
        path=f"/tmp/{id}",
    )


class _FakeService:
    """Minimal shim exposing only delete_worktrees_bulk + a scripted delete_worktree."""

    def __init__(self, behaviours: dict[str, object]):
        self._behaviours = behaviours
        self.calls: list[tuple[str, bool, bool]] = []

    async def delete_worktree(
        self, worktree_id: str, delete_branch: bool = False, force: bool = False
    ) -> None:
        self.calls.append((worktree_id, delete_branch, force))
        outcome = self._behaviours.get(worktree_id, "success")
        if outcome == "success":
            return
        if isinstance(outcome, Exception):
            raise outcome

    # Borrow the real implementation for the bulk method.
    delete_worktrees_bulk = WorktreeService.delete_worktrees_bulk


class TestDeleteWorktreesBulk:
    @pytest.mark.asyncio
    async def test_all_succeed(self):
        service = _FakeService({"a": "success", "b": "success"})
        result = await service.delete_worktrees_bulk(
            [_entry("a"), _entry("b")], delete_branch=False
        )
        assert result.succeeded == ["a", "b"]
        assert result.dirty == []
        assert result.failed == []

    @pytest.mark.asyncio
    async def test_uncommitted_changes_goes_to_dirty(self):
        dirty_entry = _entry("dirty")
        service = _FakeService({"a": "success", "dirty": UncommittedChangesError("nope")})
        result = await service.delete_worktrees_bulk(
            [_entry("a"), dirty_entry], delete_branch=True
        )
        assert result.succeeded == ["a"]
        assert result.dirty == [dirty_entry]
        assert result.failed == []

    @pytest.mark.asyncio
    async def test_not_found_treated_as_success(self):
        service = _FakeService({"gone": WorktreeNotFoundError("gone")})
        result = await service.delete_worktrees_bulk(
            [_entry("gone")], delete_branch=False
        )
        assert result.succeeded == ["gone"]
        assert result.dirty == []
        assert result.failed == []

    @pytest.mark.asyncio
    async def test_generic_exception_goes_to_failed(self):
        boom = RuntimeError("disk full")
        service = _FakeService({"a": "success", "bad": boom})
        result = await service.delete_worktrees_bulk(
            [_entry("a"), _entry("bad")], delete_branch=False
        )
        assert result.succeeded == ["a"]
        assert result.dirty == []
        assert len(result.failed) == 1
        assert result.failed[0][0] == "bad"
        assert result.failed[0][1] is boom

    @pytest.mark.asyncio
    async def test_input_list_not_mutated(self):
        entries = [_entry("a"), _entry("b")]
        service = _FakeService({"a": "success", "b": "success"})
        await service.delete_worktrees_bulk(entries, delete_branch=False)
        assert [e.id for e in entries] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_force_flag_forwarded(self):
        service = _FakeService({"a": "success"})
        await service.delete_worktrees_bulk(
            [_entry("a")], delete_branch=False, force=True
        )
        assert service.calls == [("a", False, True)]

    @pytest.mark.asyncio
    async def test_delete_branch_flag_forwarded(self):
        service = _FakeService({"a": "success"})
        await service.delete_worktrees_bulk(
            [_entry("a")], delete_branch=True, force=False
        )
        assert service.calls == [("a", True, False)]

    @pytest.mark.asyncio
    async def test_returns_bulk_delete_result(self):
        service = _FakeService({"a": "success"})
        result = await service.delete_worktrees_bulk(
            [_entry("a")], delete_branch=False
        )
        assert isinstance(result, BulkDeleteResult)
