"""Friendly, type-aware display names for terminal workspaces.

Turns a worktree's stored ``work_type`` / ``issue_id`` / ``branch`` into a
human-readable label such as ``PR Review #123`` or ``Bug 4286: Fix login``.
Pure functions only -- no I/O -- so the logic stays easy to test.
"""

from gwt_worktree_manager.store.metadata import WorktreeEntry, extract_branch_parts

# Short label per work type. Types absent here (e.g. "duplicate", "") fall back
# to parsing the branch, then to the raw branch name.
WORK_TYPE_LABELS: dict[str, str] = {
    "feature": "Feat",
    "bug": "Bug",
    "chore": "Chore",
    "doc": "Doc",
    "refactor": "Refactor",
    "hotfix": "Hotfix",
    "task": "Task",
    "pr-review": "PR Review",
}


def branch_suffix(branch: str, issue_id: str) -> str:
    """Return the description part of a branch in kebab form.

    Strips the ``type/`` prefix and any ``{issue_id}-`` prefix.

    Examples:
        ("feature/TB-12-add-login", "TB-12") -> "add-login"
        ("chore/update-deps", "")            -> "update-deps"
        ("bug/4286", "4286")                 -> ""
    """
    rest = branch.partition("/")[2] if "/" in branch else branch
    if issue_id:
        prefix = f"{issue_id}-"
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
        elif rest == issue_id:
            rest = ""
    return rest


def _sentence_case(suffix: str) -> str:
    """Kebab description -> Sentence case (capitalize the first word only)."""
    text = " ".join(word for word in suffix.split("-") if word)
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def workspace_display_name(work_type: str, issue_id: str, branch: str) -> str:
    """Compose a friendly workspace name from a worktree's metadata.

    Examples:
        ("pr-review", "123", <head-branch>)        -> "PR Review #123"
        ("bug", "4286", "bug/4286-fix-login")       -> "Bug 4286: Fix login"
        ("feature", "TB-12", "feature/TB-12-add")   -> "Feat TB-12: Add"
        ("chore", "", "chore/update-deps")          -> "Chore: Update deps"
        ("duplicate", "", "main")                    -> "main"
    """
    if work_type == "pr-review":
        return f"PR Review #{issue_id}" if issue_id else f"PR Review: {branch}"

    # Unknown/duplicate types: recover type + id from the branch itself.
    if work_type not in WORK_TYPE_LABELS:
        parsed_type, parsed_id = extract_branch_parts(branch)
        if parsed_type in WORK_TYPE_LABELS:
            work_type, issue_id = parsed_type, parsed_id
        else:
            return branch

    label = WORK_TYPE_LABELS[work_type]
    title = _sentence_case(branch_suffix(branch, issue_id))

    if issue_id and title:
        return f"{label} {issue_id}: {title}"
    if issue_id:
        return f"{label} {issue_id}"
    if title:
        return f"{label}: {title}"
    return label


def workspace_name_for(entry: WorktreeEntry) -> str:
    """Friendly workspace name for a worktree entry."""
    return workspace_display_name(entry.work_type, entry.issue_id, entry.branch)


def unique_workspace_name(desired: str, existing: set[str]) -> str:
    """Return ``desired`` if free, else the first free ``"{desired} V{n}"``.

    Versions start at ``V2`` so the first workspace keeps a clean name.
    """
    if desired not in existing:
        return desired
    n = 2
    while f"{desired} V{n}" in existing:
        n += 1
    return f"{desired} V{n}"
