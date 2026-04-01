# GWT Worktree Manager

A Python CLI and TUI tool for managing Git worktrees across multiple repositories. Create, open, delete, move, and switch worktrees with a single command.

## Requirements

- Python 3.12+
- Git 2.20+
- macOS or Linux

## Installation

```bash
# Using uv (recommended)
uv tool install .

# Using pip
pip install .

# For development
pip install -e '.[dev]'
```

After installation, the `gwt` command is available in your terminal.

## Shell Setup (Required for `cd` Integration)

The `gwt open` command needs a shell wrapper to change your working directory. Add this to your shell config:

**Zsh** (add to `~/.zshrc`):
```bash
eval "$(gwt shell-init zsh)"
```

**Bash** (add to `~/.bashrc`):
```bash
eval "$(gwt shell-init bash)"
```

Then restart your shell or run `source ~/.zshrc`.

Without this setup, `gwt open` will print the worktree path instead of navigating to it.

## Quick Start

```bash
# Create a worktree for a feature
gwt create --repo myapp --type feature --id TB-123 --desc "add user profile"

# Open a worktree by issue ID (searches all repos)
gwt open TB-123

# List all worktrees across repos
gwt list

# Delete a worktree (prompts for confirmation)
gwt delete TB-123

# Launch the full-screen TUI
gwt
```

## Commands

### `gwt create`

Create a new worktree with a standardised branch name.

```bash
gwt create --repo <name> --type <type> --id <issue-id> --desc <description> [--source <branch>]
```

| Flag | Short | Required | Description |
|------|-------|----------|-------------|
| `--repo` | `-r` | Yes | Repository name (as discovered by scan) |
| `--type` | `-t` | Yes | Work type: `feature`, `bug`, `chore`, `doc`, `refactor`, `hotfix` |
| `--id` | `-i` | Yes | Issue ID (e.g., `TB-123`, `12345`, `PROJ-1`) |
| `--desc` | `-d` | Yes | Short description (converted to kebab-case) |
| `--source` | `-s` | No | Source branch (defaults to per-repo config or global default) |

The branch is created as `{type}/{id}-{kebab-description}` and the worktree is placed at `{worktrees_dir}/{repo}/{branch}`.

**Examples:**
```bash
gwt create -r myapp -t feature -i TB-123 -d "add user profile"
# Creates: feature/TB-123-add-user-profile

gwt create -r api-service -t bug -i 45678 -d "fix login timeout" -s main
# Creates: bug/45678-fix-login-timeout (from main branch)
```

### `gwt open`

Open a worktree by issue ID. Searches across all discovered repositories.

```bash
gwt open <issue-id>
```

- **Single match**: navigates to the worktree (with shell wrapper) or prints the path
- **Multiple matches**: prompts you to select which worktree to open
- **No match**: prints an error

**Examples:**
```bash
gwt open TB-123      # Navigate to the TB-123 worktree
gwt open 45678       # Works with numeric IDs too
```

### `gwt delete`

Delete a worktree by issue ID, branch name, or path.

```bash
gwt delete <identifier> [--branch] [--force]
```

| Flag | Short | Description |
|------|-------|-------------|
| `--branch` | `-b` | Also delete the associated Git branch |
| `--force` | `-f` | Force delete even with uncommitted changes |

Always prompts for confirmation before deleting.

**Examples:**
```bash
gwt delete TB-123              # Delete the worktree, keep the branch
gwt delete TB-123 --branch     # Delete worktree AND branch
gwt delete TB-123 -b -f        # Force delete with uncommitted changes
```

### `gwt list`

List all worktrees, grouped by repository.

```bash
gwt list [--repo <name>] [--json]
```

| Flag | Short | Description |
|------|-------|-------------|
| `--repo` | `-r` | Filter to a specific repository |
| `--json` | `-j` | Output as JSON (machine-readable) |

**Examples:**
```bash
gwt list                  # List all worktrees across all repos
gwt list -r myapp         # List worktrees for myapp only
gwt list --json           # JSON output for scripting
```

### `gwt move`

Move a worktree to a new filesystem path.

```bash
gwt move <identifier> <new-path> [--force]
```

| Flag | Short | Description |
|------|-------|-------------|
| `--force` | `-f` | Move even with uncommitted changes |

**Example:**
```bash
gwt move TB-123 ~/Development/worktrees/myapp/new-location
```

### `gwt switch`

Switch the branch of an existing worktree. The target branch must exist locally and not be checked out in another worktree.

```bash
gwt switch <identifier> <branch>
```

**Example:**
```bash
gwt switch TB-123 other-branch
```

### `gwt prune`

Clean up stale worktree references and orphaned metadata. Runs in dry-run mode by default.

```bash
gwt prune [--apply]
```

| Flag | Description |
|------|-------------|
| `--apply` | Actually perform the cleanup (default is dry-run) |

**Examples:**
```bash
gwt prune            # See what would be cleaned (dry-run)
gwt prune --apply    # Actually clean up stale references
```

### `gwt shell-init`

Output the shell wrapper function for `cd` integration.

```bash
gwt shell-init [zsh|bash]    # Default: zsh
```

### Full-Screen TUI

Run `gwt` with no subcommand to launch the interactive terminal UI.

```bash
gwt
```

**Keyboard shortcuts in the TUI:**

| Key | Action |
|-----|--------|
| `c` | Create a new worktree |
| `d` | Delete the selected worktree |
| `o` | Open the selected worktree |
| `m` | Move worktree (redirects to CLI) |
| `s` | Switch branch (redirects to CLI) |
| `r` | Refresh repo and worktree lists |
| `y` | Copy worktree path to clipboard |
| `Tab` | Cycle focus between panels |
| `?` | Show keyboard shortcuts |
| `q` | Quit |

## Configuration

Configuration is stored in `~/.config/gwt/config.toml`. The tool works without a config file using sensible defaults.

### Full Configuration Reference

```toml
[general]
# Directories to scan for Git repositories
scan_paths = ["~/Development"]

# How many directory levels deep to scan
scan_depth = 3

# Where to create worktrees
worktrees_dir = "~/Development/worktrees"

# Default branch to create worktrees from
default_source_branch = "development"

# API response cache TTL in seconds
cache_ttl = 300

# --- Linear Integration ---
[integrations.linear]
enabled = true
# Name of the environment variable containing the API key
# (the key itself is NOT stored in the config file)
api_key_env = "LINEAR_API_KEY"

# --- Azure DevOps Integration ---
[integrations.ado]
enabled = false
org_url_env = "ADO_ORG_URL"
pat_env = "ADO_PAT"

# --- Per-Repository Configuration ---
# Each [repos.<name>] section configures a specific repository.
# The <name> must match the directory name of the repo.

[repos.myapp]
# Branch to create worktrees from (overrides general.default_source_branch)
source_branch = "main"

# Commands to run after creating a worktree (run in order, continue on failure)
post_create = ["pnpm install", "cp .env.example .env"]

# Command to run when opening a worktree
# "cd" (default) = change directory via shell wrapper
# Any other string = executed as a shell command in the worktree directory
open_command = "code ."

# Timeout for post-create hooks in seconds
hook_timeout = 120

# Additional environment variables to pass to hooks
# (beyond the default allowlist of PATH, HOME, USER, SHELL, TERM, LANG, etc.)
hook_env = ["NODE_ENV"]

[repos.api-service]
source_branch = "development"
post_create = ["pip install -e '.[dev]'"]
open_command = "cd"
```

### Defaults (No Config File)

If no config file exists, these defaults apply:

| Setting | Default |
|---------|---------|
| `scan_paths` | `["~/Development"]` |
| `scan_depth` | `3` |
| `worktrees_dir` | `~/Development/worktrees` |
| `default_source_branch` | `"development"` |
| `cache_ttl` | `300` (5 minutes) |
| `open_command` | `"cd"` |
| `hook_timeout` | `300` (5 minutes) |

### Integration Setup

**Linear**: Set the `LINEAR_API_KEY` environment variable and enable in config. Issue titles and status will display alongside worktrees.

**Azure DevOps**: Set `ADO_ORG_URL` (e.g., `https://dev.azure.com/myorg`) and `ADO_PAT` environment variables. Enable in config.

API credentials are never stored in the config file. The config only references the environment variable names.

## How It Works

### Repository Discovery

GWT scans your configured `scan_paths` (default: `~/Development`) up to `scan_depth` levels deep, looking for directories containing a `.git` folder. It automatically excludes:

- The `worktrees_dir` itself (to avoid listing worktrees as repos)
- Worktree checkouts (where `.git` is a file, not a directory)
- Symlinks (to prevent infinite loops)
- Hidden directories

### Branch Naming Convention

All branches follow the format: `{type}/{issueId}-{kebab-description}`

- **type**: `feature`, `bug`, `chore`, `doc`, `refactor`, or `hotfix`
- **issueId**: Alphanumeric with optional internal hyphens (e.g., `TB-123`, `12345`, `PROJ-1`)
- **description**: Converted to lowercase kebab-case automatically

### Worktree Directory Structure

Worktrees are created at: `{worktrees_dir}/{repo-name}/{branch-name}`

```
~/Development/worktrees/
  myapp/
    feature/TB-123-add-user-profile/
    bug/TB-456-fix-login/
  api-service/
    chore/TB-789-update-deps/
```

### Metadata

GWT maintains a lightweight JSON metadata file at `~/.local/share/gwt/metadata.json` tracking:

- Worktree UUID, repo name, branch, path
- Issue ID and work type (extracted from branch name)
- Creation and last-accessed timestamps
- Custom tags

This metadata is reconciled with Git's actual worktree state on every `gwt list` and TUI launch. Stale entries are automatically cleaned up.

### Post-Create Hooks

When a worktree is created, GWT runs the configured `post_create` commands in order. If no hooks are configured, it auto-detects the package manager from lock files:

| Lock File | Command |
|-----------|---------|
| `pnpm-lock.yaml` | `pnpm install` |
| `yarn.lock` | `yarn install` |
| `package-lock.json` | `npm install` |
| `bun.lockb` / `bun.lock` | `bun install` |
| `requirements.txt` | `pip install -r requirements.txt` |
| `pyproject.toml` | `pip install -e .` |

Hooks run with a sanitised environment (only essential variables like `PATH`, `HOME`, `SHELL` are passed through). API keys and other secrets are not exposed to hook processes.

### Security

- Git commands use argument lists (never `shell=True`) to prevent injection
- Hook environments use an allowlist — only safe variables are passed through
- Worktree paths are validated to prevent directory traversal
- API credentials are read from environment variables, not stored in config
- Metadata files are created with `0600` permissions
- TLS certificate verification is always enabled for API calls

## Development

```bash
# Clone and install in dev mode
git clone <repo-url>
cd gwt-helper
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=gwt_worktree_manager --cov-report=term-missing
```
