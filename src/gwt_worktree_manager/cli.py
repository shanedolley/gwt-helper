"""CLI entry point for GWT Worktree Manager."""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import typer

from gwt_worktree_manager import __version__
from gwt_worktree_manager.config.manager import load_config
from gwt_worktree_manager.store.metadata import MetadataStore, WorktreeEntry
from gwt_worktree_manager.services.discovery import RepoDiscovery
from gwt_worktree_manager.services.worktree import (
    WorktreeService,
    WorktreeNotFoundError,
    BranchExistsError,
    InvalidInputError,
    UncommittedChangesError,
    BranchCheckedOutError,
)
from gwt_worktree_manager.git import operations as git


app = typer.Typer(
    name="gwt",
    help="GWT Worktree Manager — Interactive Git worktree management",
    no_args_is_help=False,
)


def _get_service() -> WorktreeService:
    """Initialize and return the WorktreeService."""
    config = load_config()
    metadata = MetadataStore()
    discovery = RepoDiscovery(config)
    return WorktreeService(config, metadata, discovery)


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
) -> None:
    """Launch TUI if no subcommand given."""
    if version:
        typer.echo(f"gwt {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        from gwt_worktree_manager.app import run_tui
        result = run_tui()
        if result and isinstance(result, str) and result.startswith("__GWT_CD__:"):
            typer.echo(result)


@app.command()
def create(
    repo: str = typer.Option(..., "--repo", "-r", help="Repository name"),
    work_type: str = typer.Option(
        ..., "--type", "-t", help="Work type (feature/bug/chore/doc/refactor/hotfix)"
    ),
    issue_id: str = typer.Option(..., "--id", "-i", help="Issue ID (e.g., TB-123)"),
    description: str = typer.Option(..., "--desc", "-d", help="Short description"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Source branch"),
) -> None:
    """Create a new worktree with a new branch."""
    try:
        svc = _get_service()
        entry = _run(svc.create_worktree(repo, work_type, issue_id, description, source))
        typer.echo(f"Created worktree: {entry.branch}")
        typer.echo(f"Path: {entry.path}")
    except (InvalidInputError, BranchExistsError, WorktreeNotFoundError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def open(
    issue_id: str = typer.Argument(..., help="Issue ID to search for"),
) -> None:
    """Open a worktree by issue ID."""
    try:
        svc = _get_service()
        results = _run(svc.search_by_issue(issue_id))

        if not results:
            typer.echo(f"No worktree found for issue {issue_id}", err=True)
            raise typer.Exit(1)

        # If multiple matches, prompt for selection
        if len(results) > 1:
            typer.echo(f"Multiple worktrees match '{issue_id}':")
            for i, entry in enumerate(results, 1):
                typer.echo(f"  [{i}] {entry.repo_name}: {entry.branch} ({entry.path})")

            choice = typer.prompt("Select worktree", type=int)
            if choice < 1 or choice > len(results):
                typer.echo("Invalid selection", err=True)
                raise typer.Exit(1)
            target = results[choice - 1]
        else:
            target = results[0]

        result = _run(svc.open_worktree(target.id))

        if result.action == "cd":
            # Check for shell wrapper
            if not os.environ.get("GWT_SHELL_WRAPPER"):
                typer.echo(
                    "Shell wrapper not detected. To enable 'cd' integration, add to your .zshrc:\n"
                    '  eval "$(gwt shell-init zsh)"\n'
                    f"\nWorktree path: {result.cd_path}",
                    err=True,
                )
                raise typer.Exit(1)
            # Emit cd marker for shell wrapper
            typer.echo(f"__GWT_CD__:{result.cd_path}")
        else:
            # Execute the open command
            subprocess.run(
                result.command_executed,
                shell=True,
                cwd=str(result.worktree.path) if result.worktree else None,
            )
    except WorktreeNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def delete(
    identifier: str = typer.Argument(..., help="Issue ID, branch name, or worktree path"),
    branch: bool = typer.Option(False, "--branch", "-b", help="Also delete the associated branch"),
    force: bool = typer.Option(False, "--force", "-f", help="Force delete even with uncommitted changes"),
) -> None:
    """Delete a worktree."""
    try:
        svc = _get_service()
        metadata = svc.metadata

        # Resolve identifier to entry
        entry = _resolve_identifier(metadata, identifier)
        if entry is None:
            typer.echo(f"No worktree found matching '{identifier}'", err=True)
            raise typer.Exit(1)

        # Confirm
        typer.confirm(f"Delete worktree at {entry.path}?", abort=True)

        _run(svc.delete_worktree(entry.id, delete_branch=branch, force=force))
        typer.echo(f"Deleted worktree: {entry.branch}")
        if branch:
            typer.echo(f"Deleted branch: {entry.branch}")
    except (WorktreeNotFoundError, UncommittedChangesError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command("list")
def list_cmd(
    repo: Optional[str] = typer.Option(None, "--repo", "-r", help="Filter by repository"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """List all worktrees."""
    svc = _get_service()

    # Trigger reconciliation
    if not repo:
        _run(svc.reconcile_all_repos())

    entries = _run(svc.list_worktrees(repo_name=repo))

    if json_output:
        output = {
            "schema_version": 1,
            "worktrees": [
                {
                    "id": e.id,
                    "repo_name": e.repo_name,
                    "branch": e.branch,
                    "path": e.path,
                    "issue_id": e.issue_id,
                    "work_type": e.work_type,
                    "source_branch": e.source_branch,
                    "created_at": e.created_at,
                    "last_accessed": e.last_accessed,
                    "tags": e.tags,
                }
                for e in entries
            ],
        }
        typer.echo(json.dumps(output, indent=2))
    else:
        if not entries:
            typer.echo("No worktrees found.")
            return

        # Group by repo
        by_repo: dict[str, list[WorktreeEntry]] = {}
        for e in entries:
            by_repo.setdefault(e.repo_name, []).append(e)

        for repo_name, repo_entries in sorted(by_repo.items()):
            typer.echo(f"\n{repo_name}:")
            for e in repo_entries:
                issue = f" [{e.issue_id}]" if e.issue_id else ""
                typer.echo(f"  {e.branch}{issue} — {e.path}")


@app.command()
def move(
    identifier: str = typer.Argument(..., help="Issue ID, branch name, or path"),
    new_path: str = typer.Argument(..., help="New filesystem path"),
    force: bool = typer.Option(False, "--force", "-f", help="Force move with uncommitted changes"),
) -> None:
    """Move a worktree to a new filesystem path."""
    try:
        svc = _get_service()
        entry = _resolve_identifier(svc.metadata, identifier)
        if entry is None:
            typer.echo(f"No worktree found matching '{identifier}'", err=True)
            raise typer.Exit(1)

        updated = _run(svc.move_worktree(entry.id, Path(new_path)))
        typer.echo(f"Moved worktree to: {updated.path}")
    except (WorktreeNotFoundError, UncommittedChangesError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def switch(
    identifier: str = typer.Argument(..., help="Issue ID, branch name, or path"),
    branch: str = typer.Argument(..., help="Target branch to switch to"),
) -> None:
    """Switch the branch of a worktree."""
    try:
        svc = _get_service()
        entry = _resolve_identifier(svc.metadata, identifier)
        if entry is None:
            typer.echo(f"No worktree found matching '{identifier}'", err=True)
            raise typer.Exit(1)

        updated = _run(svc.switch_branch(entry.id, branch))
        typer.echo(f"Switched to branch: {updated.branch}")
    except (WorktreeNotFoundError, InvalidInputError, UncommittedChangesError, BranchCheckedOutError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def prune(
    apply: bool = typer.Option(False, "--apply", help="Actually perform cleanup (default is dry-run)"),
) -> None:
    """Clean up stale worktree references and orphaned metadata."""
    svc = _get_service()
    repos = _run(svc.get_discovered_repos())

    stale_count = 0
    for r in repos:
        try:
            worktrees = _run(git.list_worktrees(r.path))
        except git.GitError:
            continue

        # Check for entries that don't match git state
        before = {e.id for e in svc.metadata.list_all()}
        svc.metadata.reconcile(worktrees, repo_name=r.name)
        after = {e.id for e in svc.metadata.list_all()}
        removed = before - after

        for entry_id in removed:
            typer.echo(f"  Stale: {entry_id} (metadata entry, no Git worktree)")
            stale_count += 1

        if apply:
            try:
                _run(git.prune_worktrees(r.path))
            except git.GitError:
                pass

    # Check for orphaned directories under worktrees_dir
    worktrees_dir = svc.config.resolve_worktrees_dir()
    if worktrees_dir.exists():
        known_paths = {e.path for e in svc.metadata.list_all()}
        for repo_dir in worktrees_dir.iterdir():
            if not repo_dir.is_dir():
                continue
            for wt_dir in repo_dir.iterdir():
                if not wt_dir.is_dir():
                    continue
                if str(wt_dir) not in known_paths:
                    typer.echo(f"  Orphaned directory: {wt_dir}")
                    stale_count += 1
                    if apply:
                        if (wt_dir / ".git").exists():
                            typer.echo(f"  Skipped (active git repo): {wt_dir}")
                            continue
                        shutil.rmtree(wt_dir, ignore_errors=True)
                        typer.echo(f"  Removed: {wt_dir}")

    if stale_count == 0:
        typer.echo("No stale references or orphaned directories found.")
    elif not apply:
        typer.echo(f"\nFound {stale_count} item(s) to clean. Run 'gwt prune --apply' to remove.")


@app.command("shell-init")
def shell_init(
    shell: str = typer.Argument("zsh", help="Shell type (zsh or bash)"),
) -> None:
    """Output shell wrapper function for cd integration."""
    if shell == "zsh":
        typer.echo(ZSH_WRAPPER)
    elif shell == "bash":
        typer.echo(BASH_WRAPPER)
    else:
        typer.echo(f"Unsupported shell: {shell}. Use 'zsh' or 'bash'.", err=True)
        raise typer.Exit(1)


# Shell wrapper templates

ZSH_WRAPPER = """gwt() {
  export GWT_SHELL_WRAPPER=1
  local output
  output=$(command gwt "$@")
  local exit_code=$?
  if [[ "$output" =~ __GWT_CD__:(.+) ]]; then
    cd "${match[1]}"
  elif [[ -n "$output" ]]; then
    echo "$output"
  fi
  return $exit_code
}"""

BASH_WRAPPER = """gwt() {
  export GWT_SHELL_WRAPPER=1
  local output
  output=$(command gwt "$@")
  local exit_code=$?
  if [[ "$output" =~ __GWT_CD__:(.+) ]]; then
    cd "${BASH_REMATCH[1]}"
  elif [[ -n "$output" ]]; then
    echo "$output"
  fi
  return $exit_code
}"""


def _resolve_identifier(
    metadata: MetadataStore, identifier: str
) -> Optional[WorktreeEntry]:
    """Resolve a user-provided identifier to a WorktreeEntry.

    Tries in order: issue ID, branch name, path.
    """
    # Try issue ID
    matches = metadata.find_by_issue_id(identifier)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        typer.echo(f"Multiple worktrees match '{identifier}':")
        for i, e in enumerate(matches, 1):
            typer.echo(f"  [{i}] {e.repo_name}: {e.branch}")
        choice = typer.prompt("Select worktree", type=int)
        if 1 <= choice <= len(matches):
            return matches[choice - 1]
        return None

    # Try branch name
    entry = metadata.find_by_branch(identifier)
    if entry:
        return entry

    # Try path
    entry = metadata.find_by_path(identifier)
    if entry:
        return entry

    return None
