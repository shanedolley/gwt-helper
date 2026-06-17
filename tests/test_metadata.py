import pytest
import os
from pathlib import Path
from gwt_worktree_manager.store.metadata import (
    MetadataStore,
    ReconcileResult,
    WorktreeEntry,
    extract_branch_parts,
)


class FakeWT:
    """Stand-in for a git WorktreeInfo used in reconcile tests."""

    def __init__(self, path, branch=None, is_bare=False):
        self.path = path
        self.branch = branch
        self.is_bare = is_bare


@pytest.fixture
def metadata_path(tmp_path: Path) -> Path:
    """Return a temp path for metadata.json."""
    return tmp_path / "gwt" / "metadata.json"


@pytest.fixture
def store(metadata_path: Path) -> MetadataStore:
    """Create a fresh MetadataStore."""
    return MetadataStore(metadata_path=metadata_path)


def _make_entry(**overrides) -> WorktreeEntry:
    """Helper to create a WorktreeEntry with defaults."""
    import uuid

    defaults = {
        "id": str(uuid.uuid4()),
        "repo_name": "test-repo",
        "branch": "feature/TB-123-test",
        "path": "/tmp/worktrees/test-repo/feature/TB-123-test",
        "issue_id": "TB-123",
        "work_type": "feature",
        "source_branch": "main",
        "created_at": "2026-03-27T00:00:00+00:00",
        "last_accessed": "2026-03-27T00:00:00+00:00",
        "tags": [],
    }
    defaults.update(overrides)
    return WorktreeEntry(**defaults)


class TestMetadataStore:
    def test_create_and_get(self, store, metadata_path):
        entry = _make_entry()
        store.create(entry)
        retrieved = store.get(entry.id)
        assert retrieved is not None
        assert retrieved.branch == entry.branch
        assert metadata_path.exists()

    def test_create_persists_to_disk(self, metadata_path):
        store1 = MetadataStore(metadata_path=metadata_path)
        entry = _make_entry()
        store1.create(entry)

        # Load in a new instance
        store2 = MetadataStore(metadata_path=metadata_path)
        assert store2.get(entry.id) is not None

    def test_update(self, store):
        entry = _make_entry()
        store.create(entry)
        entry.tags = ["updated"]
        store.update(entry)
        assert store.get(entry.id).tags == ["updated"]

    def test_update_nonexistent_raises(self, store):
        entry = _make_entry()
        with pytest.raises(KeyError):
            store.update(entry)

    def test_delete(self, store):
        entry = _make_entry()
        store.create(entry)
        store.delete(entry.id)
        assert store.get(entry.id) is None

    def test_delete_nonexistent_raises(self, store):
        with pytest.raises(KeyError):
            store.delete("nonexistent-uuid")

    def test_find_by_issue_id(self, store):
        e1 = _make_entry(issue_id="TB-123")
        e2 = _make_entry(issue_id="TB-456")
        e3 = _make_entry(issue_id="TB-123", branch="bug/TB-123-other")
        store.create(e1)
        store.create(e2)
        store.create(e3)
        results = store.find_by_issue_id("TB-123")
        assert len(results) == 2

    def test_find_by_branch(self, store):
        entry = _make_entry(branch="feature/unique-branch")
        store.create(entry)
        found = store.find_by_branch("feature/unique-branch")
        assert found is not None
        assert found.id == entry.id

    def test_find_by_branch_not_found(self, store):
        assert store.find_by_branch("nonexistent") is None

    def test_find_by_path(self, store):
        entry = _make_entry(path="/some/unique/path")
        store.create(entry)
        found = store.find_by_path("/some/unique/path")
        assert found is not None

    def test_find_by_path_not_found(self, store):
        assert store.find_by_path("/nonexistent") is None

    def test_list_all(self, store):
        store.create(_make_entry())
        store.create(_make_entry())
        assert len(store.list_all()) == 2

    def test_empty_store(self, store):
        assert store.list_all() == []
        assert store.get("anything") is None

    def test_file_permissions(self, store, metadata_path):
        entry = _make_entry()
        store.create(entry)
        stat = os.stat(metadata_path)
        mode = stat.st_mode & 0o777
        assert mode == 0o600

    def test_corrupted_json_recovers(self, metadata_path):
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text("not valid json {{{")
        store = MetadataStore(metadata_path=metadata_path)
        assert store.list_all() == []  # Recovers with empty state

    def test_nonexistent_file_starts_empty(self, tmp_path):
        store = MetadataStore(metadata_path=tmp_path / "nope" / "metadata.json")
        assert store.list_all() == []


class TestReconcile:
    def test_removes_stale_entries(self, store):
        entry = _make_entry(path="/old/path")
        store.create(entry)

        # Simulate git worktree list with no worktrees at /old/path
        class FakeWT:
            def __init__(self, path, branch=None):
                self.path = path
                self.branch = branch
                self.is_bare = False

        store.reconcile([FakeWT("/new/path", "main")])
        assert store.get(entry.id) is None  # Stale entry removed

    def test_hydrates_missing_entries(self, store):
        class FakeWT:
            def __init__(self, path, branch):
                self.path = path
                self.branch = branch
                self.is_bare = False

        store.reconcile([FakeWT("/wt/feature/TB-789-thing", "feature/TB-789-thing")])
        entries = store.list_all()
        assert len(entries) == 1
        assert entries[0].branch == "feature/TB-789-thing"
        assert entries[0].issue_id == "TB-789"
        assert entries[0].work_type == "feature"

    def test_preserves_existing_metadata(self, store):
        entry = _make_entry(path="/existing", tags=["keep-me"])
        store.create(entry)

        class FakeWT:
            def __init__(self, path, branch):
                self.path = path
                self.branch = branch
                self.is_bare = False

        store.reconcile([FakeWT("/existing", "feature/TB-123-test")])
        preserved = store.get(entry.id)
        assert preserved is not None
        assert preserved.tags == ["keep-me"]

    def test_skips_bare_repos(self, store):
        store.reconcile([FakeWT("/bare", None, is_bare=True)])
        assert store.list_all() == []


class TestReconcileUpdatesAndCounts:
    def test_updates_changed_branch_and_rederives_fields(self, store):
        entry = _make_entry(
            path="/existing",
            branch="feature/gwt-worktree-manager",
            work_type="feature",
            issue_id="",
            issue_url="https://example.test/issue",
        )
        store.create(entry)

        store.reconcile([FakeWT("/existing", "main")])

        updated = store.get(entry.id)
        assert updated is not None
        assert updated.branch == "main"
        assert updated.work_type == ""
        assert updated.issue_id == ""
        # issue_id became empty, so the stale issue link is cleared
        assert updated.issue_url == ""

    def test_changed_branch_with_issue_rederives_issue_id(self, store):
        entry = _make_entry(
            path="/existing",
            branch="feature/TB-1-old",
            work_type="feature",
            issue_id="TB-1",
        )
        store.create(entry)

        store.reconcile([FakeWT("/existing", "bug/TB-2-new")])

        updated = store.get(entry.id)
        assert updated.branch == "bug/TB-2-new"
        assert updated.work_type == "bug"
        assert updated.issue_id == "TB-2"

    def test_changed_branch_clears_stale_issue_url_when_issue_id_changes(self, store):
        # The stored URL belongs to the old issue; switching to a different
        # issue-bearing branch must clear it (the async re-fetch repopulates).
        entry = _make_entry(
            path="/existing",
            branch="feature/TB-1-old",
            issue_id="TB-1",
            issue_url="https://example.test/TB-1",
        )
        store.create(entry)

        store.reconcile([FakeWT("/existing", "bug/TB-2-new")])

        updated = store.get(entry.id)
        assert updated.issue_id == "TB-2"
        assert updated.issue_url == ""

    def test_returns_counts_for_update_add_remove(self, store):
        # changed: branch differs; identical: branch matches; removed: absent from git
        changed = _make_entry(path="/changed", branch="feature/TB-1-a")
        identical = _make_entry(path="/identical", branch="feature/TB-9-keep")
        removed = _make_entry(path="/removed", branch="feature/TB-3-gone")
        for e in (changed, identical, removed):
            store.create(e)

        result = store.reconcile(
            [
                FakeWT("/changed", "feature/TB-1-b"),
                FakeWT("/identical", "feature/TB-9-keep"),
                FakeWT("/added", "feature/TB-4-new"),
            ]
        )

        assert isinstance(result, ReconcileResult)
        assert result.updated == 1
        assert result.added == 1
        assert result.removed == 1

    def test_no_change_skips_save(self, store):
        entry = _make_entry(path="/existing", branch="feature/TB-123-test")
        store.create(entry)

        calls = []
        store._save = lambda: calls.append(1)  # type: ignore[method-assign]

        result = store.reconcile([FakeWT("/existing", "feature/TB-123-test")])

        assert calls == []
        assert result.updated == 0
        assert result.added == 0
        assert result.removed == 0

    def test_unchanged_branch_leaves_derived_fields(self, store):
        # Pre-existing inconsistency is NOT self-healed when branch matches.
        entry = _make_entry(
            path="/existing",
            branch="feature/TB-123-test",
            work_type="wrong",
            issue_id="WRONG",
        )
        store.create(entry)

        store.reconcile([FakeWT("/existing", "feature/TB-123-test")])

        preserved = store.get(entry.id)
        assert preserved.work_type == "wrong"
        assert preserved.issue_id == "WRONG"


class TestExtractBranchParts:
    def test_feature_with_issue(self):
        assert extract_branch_parts("feature/TB-123-add-profile") == ("feature", "TB-123")

    def test_bug_with_numeric_id(self):
        assert extract_branch_parts("bug/12345-fix-login") == ("bug", "12345")

    def test_hotfix_with_project_id(self):
        assert extract_branch_parts("hotfix/PROJ-1-urgent") == ("hotfix", "PROJ-1")

    def test_simple_branch_no_type(self):
        assert extract_branch_parts("main") == ("", "")

    def test_type_only_no_id(self):
        assert extract_branch_parts("feature/") == ("feature", "")

    def test_chore_with_description(self):
        wt, iid = extract_branch_parts("chore/ABC-99-update-deps")
        assert wt == "chore"
        assert iid == "ABC-99"
