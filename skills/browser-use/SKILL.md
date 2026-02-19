---
name: browser-use
description: Automates browser interactions for web testing, form filling, screenshots, and data extraction. Use when the user needs to navigate websites, interact with web pages, fill forms, take screenshots, or extract information from web pages.
allowed-tools: Bash(browser-use:*)
---

# Browser Automation with browser-use CLI

The `browser-use` command provides fast, persistent browser automation. It maintains browser sessions across commands, enabling complex multi-step workflows.

## Installation

```bash
# Run without installing (recommended for one-off use)
uvx "browser-use[cli]" open https://example.com

# Or install permanently
uv pip install "browser-use[cli]"

# Install browser dependencies (Chromium)
browser-use install
```

## Setup

**One-line install (recommended)**
```bash
curl -fsSL https://browser-use.com/cli/install.sh | bash
```

This interactive installer lets you choose your installation mode and configures everything automatically.

**Installation modes:**
```bash
curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --remote-only  # Cloud browser only
curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --local-only   # Local browser only
curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --full         # All modes
```

| Install Mode | Available Browsers | Default | Use Case |
|--------------|-------------------|---------|----------|
| `--remote-only` | remote | remote | Sandboxed agents, CI, no GUI |
| `--local-only` | chromium, real | chromium | Local development |
| `--full` | chromium, real, remote | chromium | Full flexibility |

When only one mode is installed, it becomes the default and no `--browser` flag is needed.

**Pass API key during install:**
```bash
curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --remote-only --api-key bu_xxx
```

**Verify installation:**
```bash
browser-use doctor
```

**Setup wizard (first-time configuration):**
```bash
browser-use setup                         # Interactive setup
browser-use setup --mode local            # Configure for local browser only
browser-use setup --mode remote           # Configure for cloud browser only
browser-use setup --mode full             # Configure all modes
browser-use setup --api-key bu_xxx        # Set API key during setup
browser-use setup --yes                   # Skip interactive prompts
```

**Generate template files:**
```bash
browser-use init                          # Interactive template selection
browser-use init --list                   # List available templates
browser-use init --template basic         # Generate specific template
browser-use init --output my_script.py    # Specify output file
browser-use init --force                  # Overwrite existing files
```

**Manual cloudflared install (for tunneling):**
```bash
# macOS:
brew install cloudflared

# Linux:
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ~/.local/bin/cloudflared && chmod +x ~/.local/bin/cloudflared

# Windows:
winget install Cloudflare.cloudflared
```

## Quick Start

```bash
browser-use open https://example.com           # Navigate to URL
browser-use state                              # Get page elements with indices
browser-use click 5                            # Click element by index
browser-use type "Hello World"                 # Type text
browser-use screenshot                         # Take screenshot
browser-use close                              # Close browser
```

## Core Workflow

1. **Navigate**: `browser-use open <url>` - Opens URL (starts browser if needed)
2. **Inspect**: `browser-use state` - Returns clickable elements with indices
3. **Interact**: Use indices from state to interact (`browser-use click 5`, `browser-use input 3 "text"`)
4. **Verify**: `browser-use state` or `browser-use screenshot` to confirm actions
5. **Repeat**: Browser stays open between commands

## Browser Modes

```bash
browser-use --browser chromium open <url>      # Default: headless Chromium
browser-use --browser chromium --headed open <url>  # Visible Chromium window
browser-use --browser real open <url>          # User's Chrome with login sessions
browser-use --browser remote open <url>        # Cloud browser (requires API key)
```

- **chromium**: Fast, isolated, headless by default
- **real**: Uses your Chrome with cookies, extensions, logged-in sessions
- **remote**: Cloud-hosted browser with proxy support (requires BROWSER_USE_API_KEY)

## Commands

### Navigation
```bash
browser-use open <url>                    # Navigate to URL
browser-use back                          # Go back in history
browser-use scroll down                   # Scroll down
browser-use scroll up                     # Scroll up
browser-use scroll down --amount 1000     # Scroll by specific pixels (default: 500)
```

### Page State
```bash
browser-use state                         # Get URL, title, and clickable elements
browser-use screenshot                    # Take screenshot (outputs base64)
browser-use screenshot path.png           # Save screenshot to file
browser-use screenshot --full path.png    # Full page screenshot
```

### Interactions (use indices from `browser-use state`)
```bash
browser-use click <index>                 # Click element
browser-use type "text"                   # Type text into focused element
browser-use input <index> "text"          # Click element, then type text
browser-use keys "Enter"                  # Send keyboard keys
browser-use keys "Control+a"              # Send key combination
browser-use select <index> "option"       # Select dropdown option
```

### Tab Management
```bash
browser-use switch <tab>                  # Switch to tab by index
browser-use close-tab                     # Close current tab
browser-use close-tab <tab>               # Close specific tab
```

### JavaScript & Data
```bash
browser-use eval "document.title"         # Execute JavaScript, return result
browser-use extract "all product prices"  # Extract data using LLM (requires API key)
```

### Cookies
```bash
browser-use cookies get                   # Get all cookies
browser-use cookies get --url <url>       # Get cookies for specific URL
browser-use cookies set <name> <value>    # Set a cookie
browser-use cookies set name val --domain .example.com --secure --http-only
browser-use cookies set name val --same-site Strict  # SameSite: Strict, Lax, or None
browser-use cookies set name val --expires 1735689600  # Expiration timestamp
browser-use cookies clear                 # Clear all cookies
browser-use cookies clear --url <url>     # Clear cookies for specific URL
browser-use cookies export <file>         # Export all cookies to JSON file
browser-use cookies export <file> --url <url>  # Export cookies for specific URL
browser-use cookies import <file>         # Import cookies from JSON file
```

### Wait Conditions
```bash
browser-use wait selector "h1"            # Wait for element to be visible
browser-use wait selector ".loading" --state hidden  # Wait for element to disappear
browser-use wait selector "#btn" --state attached    # Wait for element in DOM
browser-use wait text "Success"           # Wait for text to appear
browser-use wait selector "h1" --timeout 5000  # Custom timeout in ms
```

### Additional Interactions
```bash
browser-use hover <index>                 # Hover over element (triggers CSS :hover)
browser-use dblclick <index>              # Double-click element
browser-use rightclick <index>            # Right-click element (context menu)
```

### Information Retrieval
```bash
browser-use get title                     # Get page title
browser-use get html                      # Get full page HTML
browser-use get html --selector "h1"      # Get HTML of specific element
browser-use get text <index>              # Get text content of element
browser-use get value <index>             # Get value of input/textarea
browser-use get attributes <index>        # Get all attributes of element
browser-use get bbox <index>              # Get bounding box (x, y, width, height)
```

### Python Execution (Persistent Session)
```bash
browser-use python "x = 42"               # Set variable
browser-use python "print(x)"             # Access variable (outputs: 42)
browser-use python "print(browser.url)"   # Access browser object
browser-use python --vars                 # Show defined variables
browser-use python --reset                # Clear Python namespace
browser-use python --file script.py       # Execute Python file
```

The Python session maintains state across commands. The `browser` object provides:
- `browser.url` - Current page URL
- `browser.title` - Page title
- `browser.html` - Get page HTML
- `browser.goto(url)` - Navigate
- `browser.click(index)` - Click element
- `browser.type(text)` - Type text
- `browser.input(index, text)` - Click element, then type
- `browser.keys(keys)` - Send keyboard keys (e.g., "Enter", "Control+a")
- `browser.screenshot(path)` - Take screenshot
- `browser.scroll(direction, amount)` - Scroll page
- `browser.back()` - Go back in history
- `browser.wait(seconds)` - Sleep/pause execution
- `browser.extract(query)` - Extract data using LLM

### Agent Tasks (Requires API Key)
```bash
browser-use run "Fill the contact form with test data"    # Run AI agent
browser-use run "Extract all product prices" --max-steps 50
```

Agent tasks use an LLM to autonomously complete complex browser tasks. Requires `BROWSER_USE_API_KEY` or configured LLM API key (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc).

#### Remote Mode Agent Options

When using `--browser remote`, additional options are available:

```bash
# Basic remote task (uses US proxy by default)
browser-use -b remote run "Search for AI news"

# Specify LLM model
browser-use -b remote run "task" --llm gpt-4o
browser-use -b remote run "task" --llm claude-sonnet-4-20250514
browser-use -b remote run "task" --llm gemini-2.0-flash

# Proxy configuration (default: us)
browser-use -b remote run "task" --proxy-country gb    # UK proxy
browser-use -b remote run "task" --proxy-country de    # Germany proxy

# Session reuse (run multiple tasks in same browser session)
browser-use -b remote run "task 1" --keep-alive
# Returns: session_id: abc-123
browser-use -b remote run "task 2" --session-id abc-123

# Execution modes
browser-use -b remote run "task" --no-wait     # Async, returns task_id immediately
browser-use -b remote run "task" --stream      # Stream status updates
browser-use -b remote run "task" --flash       # Fast execution mode

# Advanced options
browser-use -b remote run "task" --thinking    # Extended reasoning mode
browser-use -b remote run "task" --vision      # Enable vision (default)
browser-use -b remote run "task" --no-vision   # Disable vision
browser-use -b remote run "task" --wait        # Wait for completion (default: async)

# Use cloud profile (preserves cookies across sessions)
browser-use -b remote run "task" --profile <cloud-profile-id>

# Task configuration
browser-use -b remote run "task" --start-url https://example.com  # Start from specific URL
browser-use -b remote run "task" --allowed-domain example.com     # Restrict navigation (repeatable)
browser-use -b remote run "task" --metadata key=value             # Task metadata (repeatable)
browser-use -b remote run "task" --secret API_KEY=xxx             # Task secrets (repeatable)
browser-use -b remote run "task" --skill-id skill-123             # Enable skills (repeatable)

# Structured output and evaluation
browser-use -b remote run "task" --structured-output '{"type":"object"}'  # JSON schema for output
browser-use -b remote run "task" --judge                 # Enable judge mode
browser-use -b remote run "task" --judge-ground-truth "expected answer"   # Expected answer for judge
```

### Task Management (Remote Mode)

Manage cloud tasks when using remote mode:

```bash
browser-use task list                     # List recent tasks
browser-use task list --limit 20          # Show more tasks
browser-use task list --status running    # Filter by status
browser-use task list --session <id>      # Filter by session ID
browser-use task list --json              # JSON output

browser-use task status <task-id>         # Get task status (token efficient)
browser-use task status <task-id> -c      # Show all steps with reasoning
browser-use task status <task-id> -v      # Show all steps with URLs + actions
browser-use task status <task-id> --last 5  # Show only last 5 steps
browser-use task status <task-id> --step 3  # Show specific step number
browser-use task status <task-id> --reverse # Show steps newest first

browser-use task stop <task-id>           # Stop a running task
browser-use task logs <task-id>           # Get task execution logs
```

**Token-efficient monitoring:** Default `task status` shows only the latest step. Use `-c` (compact) or `-v` (verbose) only when you need more context.

### Cloud Session Management (Remote Mode)

Manage cloud browser sessions:

```bash
browser-use session list                  # List cloud sessions
browser-use session list --limit 20       # Show more sessions
browser-use session list --status active  # Filter by status
browser-use session list --json           # JSON output

browser-use session get <session-id>      # Get session details
browser-use session get <session-id> --json

browser-use session stop <session-id>     # Stop a session
browser-use session stop --all            # Stop all active sessions

# Create a new cloud session manually
browser-use session create                          # Create with defaults
browser-use session create --profile <id>           # With cloud profile
browser-use session create --proxy-country gb       # With geographic proxy
browser-use session create --start-url https://example.com  # Start at URL
browser-use session create --screen-size 1920x1080  # Custom screen size
browser-use session create --keep-alive             # Keep session alive
browser-use session create --persist-memory         # Persist memory between tasks

# Share session publicly (for collaboration/debugging)
browser-use session share <session-id>    # Create public share URL
browser-use session share <session-id> --delete  # Delete public share
```

## Exposing Local Dev Servers

If you're running a dev server locally and need a cloud browser to reach it, use Cloudflare tunnels:

```bash
# Start your dev server
npm run dev &  # localhost:3000

# Expose it via Cloudflare tunnel
browser-use tunnel 3000
# → url: https://abc.trycloudflare.com

# Now the cloud browser can reach your local server
browser-use --browser remote open https://abc.trycloudflare.com
```

**Tunnel commands:**
```bash
browser-use tunnel <port>           # Start tunnel (returns URL)
browser-use tunnel <port>           # Idempotent - returns existing URL
browser-use tunnel list             # Show active tunnels
browser-use tunnel stop <port>      # Stop tunnel
browser-use tunnel stop --all       # Stop all tunnels
```

**Note:** Tunnels are independent of browser sessions. They persist across `browser-use close` and can be managed separately.

Cloudflared is installed by `install.sh`. If missing, install manually (see Setup section).

## Running Subagents (Remote Mode)

Cloud sessions and tasks provide a powerful model for running **subagents** - autonomous browser agents that execute tasks in parallel.

### Key Concepts

- **Session = Agent**: Each cloud session is a browser agent with its own state (cookies, tabs, history)
- **Task = Work**: Tasks are jobs given to an agent. An agent can run multiple tasks sequentially
- **Parallel agents**: Run multiple sessions simultaneously for parallel work
- **Session reuse**: While a session is alive, you can assign it more tasks
- **Session lifecycle**: Once stopped, a session cannot be revived - start a new one

### Basic Subagent Workflow

```bash
# 1. Start a subagent task (creates new session automatically)
browser-use -b remote run "Search for AI news and summarize top 3 articles" --no-wait
# Returns: task_id: task-abc, session_id: sess-123

# 2. Check task progress
browser-use task status task-abc
# Shows: Status: running, or finished with output

# 3. View execution logs
browser-use task logs task-abc
```

### Running Parallel Subagents

Launch multiple agents to work simultaneously:

```bash
# Start 3 parallel research agents
browser-use -b remote run "Research competitor A pricing" --no-wait
# → task_id: task-1, session_id: sess-a

browser-use -b remote run "Research competitor B pricing" --no-wait
# → task_id: task-2, session_id: sess-b

browser-use -b remote run "Research competitor C pricing" --no-wait
# → task_id: task-3, session_id: sess-c

# Monitor all running tasks
browser-use task list --status running
# Shows all 3 tasks with their status

# Check individual task results as they complete
browser-use task status task-1
browser-use task status task-2
browser-use task status task-3
```

### Reusing an Agent for Multiple Tasks

Keep a session alive to run sequential tasks in the same browser context:

```bash
# Start first task, keep session alive
browser-use -b remote run "Log into example.com" --keep-alive --no-wait
# → task_id: task-1, session_id: sess-123

# Wait for login to complete...
browser-use task status task-1
# → Status: finished

# Give the same agent another task (reuses login session)
browser-use -b remote run "Navigate to settings and export data" --session-id sess-123 --no-wait
# → task_id: task-2, session_id: sess-123 (same session!)

# Agent retains cookies, login state, etc. from previous task
```

### Managing Active Agents

```bash
# List all active agents (sessions)
browser-use session list --status active
# Shows: sess-123 [active], sess-456 [active], ...

# Get details on a specific agent
browser-use session get sess-123
# Shows: status, started time, live URL for viewing

# Stop a specific agent
browser-use session stop sess-123

# Stop all agents at once
browser-use session stop --all
```

### Stopping Tasks vs Sessions

```bash
# Stop a running task (session may continue if --keep-alive was used)
browser-use task stop task-abc

# Stop an entire agent/session (terminates all its tasks)
browser-use session stop sess-123
```

### Custom Agent Configuration

```bash
# Default: US proxy, auto LLM selection
browser-use -b remote run "task" --no-wait

# Explicit configuration
browser-use -b remote run "task" \
  --llm gpt-4o \
  --proxy-country gb \
  --keep-alive \
  --no-wait

# With cloud profile (preserves cookies across sessions)
browser-use -b remote run "task" --profile <profile-id> --no-wait
```

### Monitoring Subagents

**Task status is designed for token efficiency.** Default output is minimal - only expand when needed:

| Mode | Flag | Tokens | Use When |
|------|------|--------|----------|
| Default | (none) | Low | Polling progress |
| Compact | `-c` | Medium | Need full reasoning |
| Verbose | `-v` | High | Debugging actions |

**Recommended workflow:**

```bash
# 1. Launch task
browser-use -b remote run "task" --no-wait
# → task_id: abc-123

# 2. Poll with default (token efficient) - only latest step
browser-use task status abc-123
# ✅ abc-123... [finished] $0.009 15s
#   ... 1 earlier steps
#   2. I found the information and extracted...

# 3. ONLY IF task failed or need context: use --compact
browser-use task status abc-123 -c

# 4. ONLY IF debugging specific actions: use --verbose
browser-use task status abc-123 -v
```

**For long tasks (50+ steps):**
```bash
browser-use task status <id> -c --last 5   # Last 5 steps only
browser-use task status <id> -c --reverse  # Newest first
browser-use task status <id> -v --step 10  # Inspect specific step
```

**Live view**: Watch an agent work in real-time:
```bash
browser-use session get <session-id>
# → Live URL: https://live.browser-use.com?wss=...
# Open this URL in your browser to watch the agent
```

**Detect stuck tasks**: If cost/duration stops increasing, the task may be stuck:
```bash
browser-use task status <task-id>
# 🔄 abc-123... [started] $0.009 45s  ← if cost doesn't change, task is stuck
```

**Logs**: Only available after task completes:
```bash
browser-use task logs <task-id>  # Works after task finishes
```

### Cleanup

Always clean up sessions after parallel work:
```bash
# Stop all active agents
browser-use session stop --all

# Or stop specific sessions
browser-use session stop <session-id>
```

### Troubleshooting Subagents

**Session reuse fails after `task stop`**:
If you stop a task and try to reuse its session, the new task may get stuck at "created" status. Solution: create a new agent instead.
```bash
# This may fail:
browser-use task stop <task-id>
browser-use -b remote run "new task" --session-id <same-session>  # Might get stuck

# Do this instead:
browser-use -b remote run "new task" --profile <profile-id>  # Fresh session
```

**Task stuck at "started"**:
- Check cost with `task status` - if not increasing, task is stuck
- View live URL with `session get` to see what's happening
- Stop the task and create a new agent

**Sessions persist after tasks complete**:
Tasks finishing doesn't auto-stop sessions. Clean up manually:
```bash
browser-use session list --status active  # See lingering sessions
browser-use session stop --all            # Clean up
```

### Session Management
```bash
browser-use sessions                      # List active sessions
browser-use close                         # Close current session
browser-use close --all                   # Close all sessions
```

### Profile Management

#### Local Chrome Profiles (`--browser real`)
```bash
browser-use -b real profile list          # List local Chrome profiles
```

**Before opening a real browser (`--browser real`)**, always ask the user if they want to use a specific Chrome profile or no profile. Use `profile list` to show available profiles:

```bash
browser-use -b real profile list
# Output: Default: Person 1 (user@gmail.com)
#         Profile 1: Work (work@company.com)

# With a specific profile (has that profile's cookies/logins)
browser-use --browser real --profile "Profile 1" open https://gmail.com

# Without a profile (fresh browser, no existing logins)
browser-use --browser real open https://gmail.com

# Headless mode (no visible window) - useful for cookie export
browser-use --browser real --profile "Default" cookies export /tmp/cookies.json
```

Each Chrome profile has its own cookies, history, and logged-in sessions. Choosing the right profile determines whether sites will be pre-authenticated.

#### Cloud Profiles (`--browser remote`)

Cloud profiles store browser state (cookies) in Browser-Use Cloud, persisting across sessions. Requires `BROWSER_USE_API_KEY`.

```bash
browser-use -b remote profile list            # List cloud profiles
browser-use -b remote profile list --page 2 --page-size 50  # Pagination
browser-use -b remote profile get <id>        # Get profile details
browser-use -b remote profile create          # Create new cloud profile
browser-use -b remote profile create --name "My Profile"  # Create with name
browser-use -b remote profile update <id> --name "New"    # Rename profile
browser-use -b remote profile delete <id>     # Delete profile
```

Use a cloud profile with `--browser remote --profile <id>`:

```bash
browser-use --browser remote --profile abc-123 open https://example.com
```

### Syncing Cookies to Cloud

**⚠️ IMPORTANT: Before syncing cookies from a local browser to the cloud, the agent MUST:**
1. Ask the user which local Chrome profile to use (`browser-use -b real profile list`)
2. Ask which domain(s) to sync - do NOT default to syncing the full profile
3. Confirm before proceeding

**Default behavior:** Create a NEW cloud profile for each domain sync. This ensures clear separation of concerns for cookies. Users can add cookies to existing profiles if needed.

**Step 1: List available profiles and cookies**

```bash
# List local Chrome profiles
browser-use -b real profile list
# → Default: Person 1 (user@gmail.com)
# → Profile 1: Work (work@company.com)

# See what cookies are in a profile
browser-use -b real profile cookies "Default"
# → youtube.com: 23
# → google.com: 18
# → github.com: 2
```

**Step 2: Sync cookies (three levels of control)**

**1. Domain-specific sync (recommended default)**
```bash
browser-use profile sync --from "Default" --domain youtube.com
# Creates new cloud profile: "Chrome - Default (youtube.com)"
# Only syncs youtube.com cookies
```
This is the recommended approach - sync only the cookies you need.

**2. Full profile sync (use with caution)**
```bash
browser-use profile sync --from "Default"
# Syncs ALL cookies from the profile
```
⚠️ **Warning:** This syncs ALL cookies including sensitive data, tracking cookies, session tokens for every site, etc. Only use when the user explicitly needs their entire browser state.

**3. Fine-grained control (advanced)**
```bash
# Export cookies to file
browser-use --browser real --profile "Default" cookies export /tmp/cookies.json

# Manually edit the JSON to keep only specific cookies

# Import to cloud profile
browser-use --browser remote --profile <id> cookies import /tmp/cookies.json
```
For users who need individual cookie-level control.

**Step 3: Use the synced profile**

```bash
browser-use --browser remote --profile <id> open https://youtube.com
```

**Adding cookies to existing profiles:**
```bash
# Sync additional domain to existing profile
browser-use --browser real --profile "Default" cookies export /tmp/cookies.json
browser-use --browser remote --profile <existing-id> cookies import /tmp/cookies.json
```

**Managing profiles:**
```bash
browser-use profile update <id> --name "New Name"  # Rename
browser-use profile delete <id>                    # Delete
```

### Server Control
```bash
browser-use server status                 # Check if server is running
browser-use server stop                   # Stop server
browser-use server logs                   # View server logs
```

### Setup
```bash
browser-use install                       # Install Chromium and system dependencies
```

## Global Options

| Option | Description |
|--------|-------------|
| `--session NAME` | Use named session (default: "default") |
| `--browser MODE` | Browser mode: chromium, real, remote |
| `--headed` | Show browser window (chromium mode) |
| `--profile NAME` | Browser profile (local name or cloud ID) |
| `--json` | Output as JSON |
| `--api-key KEY` | Override API key |
| `--mcp` | Run as MCP server via stdin/stdout |

**Session behavior**: All commands without `--session` use the same "default" session. The browser stays open and is reused across commands. Use `--session NAME` to run multiple browsers in parallel.

## API Key Configuration

Some features (`run`, `extract`, `--browser remote`) require an API key. The CLI checks these locations in order:

1. `--api-key` command line flag
2. `BROWSER_USE_API_KEY` environment variable
3. `~/.config/browser-use/config.json` file

To configure permanently:
```bash
mkdir -p ~/.config/browser-use
echo '{"api_key": "your-key-here"}' > ~/.config/browser-use/config.json
```

## Examples

### Form Submission
```bash
browser-use open https://example.com/contact
browser-use state
# Shows: [0] input "Name", [1] input "Email", [2] textarea "Message", [3] button "Submit"
browser-use input 0 "John Doe"
browser-use input 1 "john@example.com"
browser-use input 2 "Hello, this is a test message."
browser-use click 3
browser-use state  # Verify success
```

### Multi-Session Workflows
```bash
browser-use --session work open https://work.example.com
browser-use --session personal open https://personal.example.com
browser-use --session work state    # Check work session
browser-use --session personal state  # Check personal session
browser-use close --all             # Close both sessions
```

### Data Extraction with Python
```bash
browser-use open https://example.com/products
browser-use python "
products = []
for i in range(20):
    browser.scroll('down')
browser.screenshot('products.png')
"
browser-use python "print(f'Captured {len(products)} products')"
```

### Using Real Browser (Logged-In Sessions)
```bash
browser-use --browser real open https://gmail.com
# Uses your actual Chrome with existing login sessions
browser-use state  # Already logged in!
```

## Common Patterns

### Test a Local Dev Server with Cloud Browser

```bash
# Start dev server
npm run dev &  # localhost:3000

# Tunnel it
browser-use tunnel 3000
# → url: https://abc.trycloudflare.com

# Browse with cloud browser
browser-use --browser remote open https://abc.trycloudflare.com
browser-use state
browser-use screenshot
```

### Screenshot Loop for Visual Verification

```bash
browser-use open https://example.com
for i in 1 2 3 4 5; do
  browser-use scroll down
  browser-use screenshot "page_$i.png"
done
```

## Tips

1. **Always run `browser-use state` first** to see available elements and their indices
2. **Use `--headed` for debugging** to see what the browser is doing
3. **Sessions persist** - the browser stays open between commands
4. **Use `--json` for parsing** output programmatically
5. **Python variables persist** across `browser-use python` commands within a session
6. **Real browser mode** preserves your login sessions and extensions
7. **CLI aliases**: `bu`, `browser`, and `browseruse` all work identically to `browser-use`

## Troubleshooting

**Run diagnostics first:**
```bash
browser-use doctor                    # Check installation status
```

**Browser won't start?**
```bash
browser-use install                   # Install/reinstall Chromium
browser-use server stop               # Stop any stuck server
browser-use --headed open <url>       # Try with visible window
```

**Element not found?**
```bash
browser-use state                     # Check current elements
browser-use scroll down               # Element might be below fold
browser-use state                     # Check again
```

**Session issues?**
```bash
browser-use sessions                  # Check active sessions
browser-use close --all               # Clean slate
browser-use open <url>                # Fresh start
```

## Cleanup

**Always close the browser when done.** Run this after completing browser automation:

```bash
browser-use close
```
