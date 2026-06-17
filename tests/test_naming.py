from gwt_worktree_manager.naming import (
    branch_suffix,
    unique_workspace_name,
    workspace_display_name,
    workspace_name_for,
)
from gwt_worktree_manager.store.metadata import WorktreeEntry


class TestWorkspaceDisplayName:
    def test_pr_review_uses_pr_number(self):
        assert workspace_display_name("pr-review", "123", "feat/whatever") == "PR Review #123"

    def test_pr_review_without_id_falls_back_to_branch(self):
        assert workspace_display_name("pr-review", "", "some-head-branch") == "PR Review: some-head-branch"

    def test_bug_with_id_and_suffix_sentence_case(self):
        name = workspace_display_name("bug", "4286", "bug/4286-fix-login-redirect")
        assert name == "Bug 4286: Fix login redirect"

    def test_feature_short_label_with_project_id(self):
        name = workspace_display_name("feature", "TB-12", "feature/TB-12-add-login")
        assert name == "Feat TB-12: Add login"

    def test_chore_without_id(self):
        name = workspace_display_name("chore", "", "chore/update-deps")
        assert name == "Chore: Update deps"

    def test_each_label_is_short(self):
        cases = {
            ("doc", "D-1", "doc/D-1-readme"): "Doc D-1: Readme",
            ("refactor", "9", "refactor/9-extract-helper"): "Refactor 9: Extract helper",
            ("hotfix", "", "hotfix/patch-crash"): "Hotfix: Patch crash",
            ("task", "T-3", "task/T-3-cleanup"): "Task T-3: Cleanup",
        }
        for (wt, iid, branch), expected in cases.items():
            assert workspace_display_name(wt, iid, branch) == expected

    def test_id_without_suffix(self):
        assert workspace_display_name("bug", "4286", "bug/4286") == "Bug 4286"

    def test_label_only_when_no_id_no_suffix(self):
        assert workspace_display_name("chore", "", "chore/") == "Chore"

    def test_duplicate_parsed_when_branch_is_typed(self):
        name = workspace_display_name("duplicate", "", "feature/TB-9-extract")
        assert name == "Feat TB-9: Extract"

    def test_duplicate_falls_back_to_raw_branch(self):
        assert workspace_display_name("duplicate", "", "main") == "main"
        assert workspace_display_name("duplicate", "", "release/v2") == "release/v2"

    def test_unknown_type_falls_back_to_raw_branch(self):
        assert workspace_display_name("", "", "random-branch") == "random-branch"


class TestBranchSuffix:
    def test_strips_type_and_issue_id(self):
        assert branch_suffix("feature/TB-12-add-login", "TB-12") == "add-login"

    def test_no_issue_id(self):
        assert branch_suffix("chore/update-deps", "") == "update-deps"

    def test_id_with_no_description(self):
        assert branch_suffix("bug/4286", "4286") == ""

    def test_branch_without_slash(self):
        assert branch_suffix("main", "") == "main"


class TestWorkspaceNameForEntry:
    def test_reads_entry_fields(self):
        entry = WorktreeEntry(
            id="x", repo_name="r", branch="bug/4286-fix-login",
            path="/tmp/x", issue_id="4286", work_type="bug",
        )
        assert workspace_name_for(entry) == "Bug 4286: Fix login"


class TestUniqueWorkspaceName:
    def test_free_name_returned_as_is(self):
        assert unique_workspace_name("Feat TB-12: Add login", set()) == "Feat TB-12: Add login"

    def test_single_collision_becomes_v2(self):
        existing = {"Feat TB-12: Add login"}
        assert unique_workspace_name("Feat TB-12: Add login", existing) == "Feat TB-12: Add login V2"

    def test_chained_collisions_increment(self):
        existing = {"main", "main V2"}
        assert unique_workspace_name("main", existing) == "main V3"

    def test_skips_gaps(self):
        existing = {"main", "main V3"}
        assert unique_workspace_name("main", existing) == "main V2"
