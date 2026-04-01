# GWT Worktree Manager

A fast, interactive Git worktree manager with a full-screen TUI and CLI. Create, open, review, and manage worktrees across all your repositories from one place.

## Requirements

- Python 3.12+
- Git 2.20+
- macOS, Linux, or Windows

## Installation

```bash
# Using uv (recommended)
uv tool install .

# Using pip
pip install .

# Using pipx
pipx install .
```

After installation, run the setup wizard:

```bash
gwt setup
```

The wizard will:
- Detect your OS, terminals, editors, and AI assistants
- Configure your scan paths and worktree directory
- Check and install the GitHub CLI (`gh`) if needed
- Set up Azure DevOps and Linear integrations
- Write your config to `~/.config/gwt/config.toml`

## Shell Setup

For `cd` integration (so `gwt open` can change your directory), add one line to your shell config:

**Zsh** (add to `~/.zshrc`):
```bash
eval "$(gwt shell-init zsh)"
```

**Bash** (add to `~/.bashrc`):
```bash
eval "$(gwt shell-init bash)"
```

**Fish** (add to `~/.config/fish/config.fish`):
```fish
gwt shell-init fish | source
```

**PowerShell** (add to `$PROFILE`):
```powershell
Invoke-Expression (gwt shell-init powershell)
```

Then restart your shell.

## Quick Start

### Launch the TUI

```bash
gwt
```

This opens the full-screen interactive interface with repository browser, worktree list, and detail panel.

### TUI Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `ctrl+n` | Create a new worktree |
| `ctrl+d` | Delete the selected worktree |
| `ctrl+o` | Open worktree in terminal/multiplexer |
| `ctrl+e` | Open worktree in editor |
| `ctrl+r` | Refresh repository and worktree lists |
| `ctrl+y` | Copy worktree path to clipboard |
| `ctrl+u` | Open issue URL in browser |
| `ctrl+q` | Quit |
| `ctrl+p` | Command palette (search all actions) |
| `Tab` | Cycle focus between panels |
| `?` | Show keyboard shortcuts |
| Type any character | Filter the focused list |
| `Escape` | Clear filter / close filter |

### CLI Commands

```bash
# Create a worktree
gwt create --repo myapp --type feature --id TB-123 --desc "add user profile"

# Create without an issue ID
gwt create --repo myapp --type chore --desc "update dependencies"

# Open a worktree by issue ID
gwt open TB-123

# List all worktrees
gwt list
gwt list --repo myapp --json

# Delete a worktree
gwt delete TB-123
gwt delete TB-123 --branch --force

# Move a worktree
gwt move TB-123 ~/new/path

# Switch branch in a worktree
gwt switch TB-123 other-branch

# Clean up stale references
gwt prune --apply

# Re-run setup wizard
gwt setup
```

## Work Types

When creating a worktree, choose a work type that determines the branch name prefix:

| Type | Example Branch |
|------|---------------|
| `feature` | `feature/TB-123-add-user-profile` |
| `bug` | `bug/4286-fix-login-timeout` |
| `task` | `task/update-ci-pipeline` |
| `chore` | `chore/update-dependencies` |
| `doc` | `doc/api-documentation` |
| `refactor` | `refactor/TB-100-simplify-auth` |
| `hotfix` | `hotfix/5001-critical-fix` |
| `pr-review` | Opens PR branch in a review worktree |

### PR Review Workflow

Select `pr-review` as the work type to review a pull request:

1. Enter the PR number (or paste a full PR URL)
2. Click **Search** to resolve the branch name via `gh pr view`
3. Click **Create** to check out the PR branch in a new worktree at `worktrees/<repo>/pr-review/<PR#>`

The PR branch is fetched and checked out as-is (no new branch created).

## Terminal Support

GWT opens worktrees in your configured terminal or multiplexer. After creating or opening a worktree, it launches automatically.

| Terminal | macOS | Linux | Windows |
|----------|-------|-------|---------|
| **cmux** (recommended) | Creates workspace with AI assistant + lazygit tabs | | |
| **tmux** | Creates session with AI assistant + lazygit windows | Same | |
| **Ghostty** | Opens at worktree path | | |
| **iTerm2** | Opens at worktree path | | |
| **Alacritty** | `--working-directory` | `--working-directory` | |
| **Kitty** | `--working-directory` | `--working-directory` | |
| **WezTerm** | `--working-directory` | `--working-directory` | |
| **Windows Terminal** | | | `wt -d <path>` |
| **GNOME Terminal** | | `--working-directory` | |
| **Konsole** | | `--workdir` | |

Configure your default in `gwt setup` or in `config.toml`:

```toml
[general]
terminal = "cmux"       # or "tmux", "ghostty", "alacritty", etc.
ai_assistant = "claude"  # or "opencode", "none"
```

## Editor Support

Press `ctrl+e` in the TUI to open the selected worktree in your editor:

| Editor | Command |
|--------|---------|
| VS Code | `code <path>` |
| Cursor | `cursor <path>` |
| Neovim | `nvim <path>` |
| Zed | `zed <path>` |
| IntelliJ IDEA | `idea <path>` |
| Sublime Text | `subl <path>` |

Configure in `config.toml`:

```toml
[general]
editor = "code"  # CLI command for your editor
```

## Configuration

Config is stored at `~/.config/gwt/config.toml` (macOS/Linux) or `%APPDATA%\gwt\config.toml` (Windows). Run `gwt setup` to generate it interactively.

### Example Config

```toml
[general]
scan_paths = ["~/Development"]
worktrees_dir = "~/Development/worktrees"
default_source_branch = "main"
default_issue_tracker = "ado"
terminal = "cmux"
ai_assistant = "claude"
editor = "code"
git_hosting = "github"

[integrations.linear]
enabled = true
api_key_env = "LINEAR_API_KEY"

[integrations.ado]
enabled = true
org_url_env = "ADO_ORG_URL"
pat_env = "ADO_PAT"

[repos.myapp]
source_branch = "main"
post_create = ["pnpm install", "cp .env.example .env"]
hook_timeout = 120
```

### Per-Repository Settings

Each `[repos.<name>]` section overrides defaults for that repository:

| Setting | Description |
|---------|-------------|
| `source_branch` | Branch to create worktrees from |
| `post_create` | Commands to run after worktree creation |
| `open_command` | Command for `gwt open` in CLI mode |
| `hook_timeout` | Timeout for post-create hooks (seconds) |
| `hook_env` | Extra environment variables to pass to hooks |
| `issue_url_template` | URL template with `{issue_id}` placeholder |

### Integration Setup

**GitHub**: The `gh` CLI is used for PR review workflows. Install via `gwt setup` or manually:
```bash
brew install gh      # macOS
sudo apt install gh  # Ubuntu/Debian
winget install GitHub.cli  # Windows
```

**Linear**: Set the `LINEAR_API_KEY` environment variable. Issue titles and status display alongside worktrees.

**Azure DevOps**: Set `ADO_ORG_URL` and `ADO_PAT` environment variables. The Azure CLI (`az`) is used for authentication.

API credentials are never stored in the config file.

## How It Works

### Repository Discovery

GWT scans `scan_paths` for directories containing `.git`, automatically excluding worktree checkouts, symlinks, hidden directories, and the worktrees directory itself.

### Branch Naming

| With Issue ID | Without Issue ID |
|---------------|-----------------|
| `{type}/{issueId}-{kebab-description}` | `{type}/{kebab-description}` |
| `feature/TB-123-add-user-profile` | `chore/update-dependencies` |

### Directory Structure

```
~/Development/worktrees/
  myapp/
    feature/TB-123-add-user-profile/
    bug/4286-fix-login/
    pr-review/757/
  api-service/
    task/update-ci-pipeline/
```

### Metadata

Lightweight JSON metadata at `~/.local/share/gwt/metadata.json` (or `%LOCALAPPDATA%\gwt\` on Windows) tracks worktree state and is automatically reconciled with Git on every launch.

### Post-Create Hooks

After creating a worktree, configured `post_create` commands run automatically. If none are configured, GWT auto-detects the package manager from lock files (pnpm, yarn, npm, bun, pip).

Hooks run with a sanitised environment — only essential variables are passed through.

## Development

```bash
git clone https://github.com/shanedolley/gwt-helper.git
cd gwt-helper
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=gwt_worktree_manager --cov-report=term-missing
```
