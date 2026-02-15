---
name: remote-browser
description: Controls a cloud browser from a sandboxed remote machine. Use when the agent is running in a sandbox (no GUI) and needs to navigate websites, interact with web pages, fill forms, take screenshots, or expose local dev servers via tunnels.
allowed-tools: Bash(browser-use:*)
---

# Remote Browser Automation for Sandboxed Agents

This skill is for agents running on **sandboxed remote machines** (cloud VMs, CI, coding agents) that need to control a browser. Install `browser-use` and drive a cloud browser — no local Chrome needed.

## Setup

**Remote-only install (recommended for sandboxed agents)**
```bash
curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --remote-only
```

This configures browser-use to only use cloud browsers:
- No Chromium download (~300MB saved)
- `browser-use open <url>` automatically uses remote mode (no `--browser` flag needed)
- If API key is available, you can also pass it during install:
  ```bash
  curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --remote-only --api-key bu_xxx
  ```

**Manual install (alternative)**
```bash
pip install "browser-use[cli]"

# Install cloudflared for tunneling:
# macOS:
brew install cloudflared

# Linux:
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ~/.local/bin/cloudflared && chmod +x ~/.local/bin/cloudflared

# Windows:
winget install Cloudflare.cloudflared
```

**Then configure your API key:**
```bash
export BROWSER_USE_API_KEY=bu_xxx   # Required for cloud browser
```

**Verify installation:**
```bash
browser-use doctor
```

## Core Workflow

When installed with `--remote-only`, commands automatically use the cloud browser — no `--browser` flag needed:

```bash
# Step 1: Start session (automatically uses remote mode)
browser-use open https://example.com
# Returns: url, live_url (view the browser in real-time)

# Step 2+: All subsequent commands use the existing session
browser-use state                   # Get page elements with indices
browser-use click 5                 # Click element by index
browser-use type "Hello World"      # Type into focused element
browser-use input 3 "text"          # Click element, then type
browser-use screenshot              # Take screenshot (base64)
browser-use screenshot page.png     # Save screenshot to file

# Done: Close the session
browser-use close                   # Close browser and release resources
```

### Understanding Installation Modes

| Install Command | Available Modes | Default Mode | Use Case |
|-----------------|-----------------|--------------|----------|
| `--remote-only` | remote | remote | Sandboxed agents, no GUI |
| `--local-only` | chromium, real | chromium | Local development |
| `--full` | chromium, real, remote | chromium | Full flexibility |

When only one mode is installed, it becomes the default and no `--browser` flag is needed.

## Exposing Local Dev Servers

If you're running a dev server on the remote machine and need the cloud browser to reach it:

```bash
# Start your dev server
python -m http.server 3000 &

# Expose it via Cloudflare tunnel
browser-use tunnel 3000
# → url: https://abc.trycloudflare.com

# Now the cloud browser can reach your local server
browser-use open https://abc.trycloudflare.com
```

Tunnel commands:
```bash
browser-use tunnel <port>           # Start tunnel (returns URL)
browser-use tunnel <port>           # Idempotent - returns existing URL
browser-use tunnel list             # Show active tunnels
browser-use tunnel stop <port>      # Stop tunnel
browser-use tunnel stop --all       # Stop all tunnels
```

**Note:** Tunnels are independent of browser sessions. They persist across `browser-use close` and can be managed separately.

Cloudflared is installed by `install.sh --remote-only`. If missing, install manually (see Setup section).

## Commands

### Navigation
```bash
browser-use open <url>              # Navigate to URL
browser-use back                    # Go back in history
browser-use scroll down             # Scroll down
browser-use scroll up               # Scroll up
browser-use scroll down --amount 1000  # Scroll by specific pixels (default: 500)
```

### Page State
```bash
browser-use state                   # Get URL, title, and clickable elements
browser-use screenshot              # Take screenshot (base64)
browser-use screenshot path.png     # Save screenshot to file
browser-use screenshot --full p.png # Full page screenshot
```

### Interactions (use indices from `state`)
```bash
browser-use click <index>           # Click element
browser-use type "text"             # Type into focused element
browser-use input <index> "text"    # Click element, then type
browser-use keys "Enter"            # Send keyboard keys
browser-use keys "Control+a"        # Key combination
browser-use select <index> "option" # Select dropdown option
browser-use hover <index>           # Hover over element
browser-use dblclick <index>        # Double-click
browser-use rightclick <index>      # Right-click
```

### JavaScript & Data
```bash
browser-use eval "document.title"   # Execute JavaScript
browser-use extract "all prices"    # Extract data using LLM
browser-use get title               # Get page title
browser-use get html                # Get page HTML
browser-use get html --selector "h1"  # Scoped HTML
browser-use get text <index>        # Get element text
browser-use get value <index>       # Get input value
browser-use get attributes <index>  # Get element attributes
browser-use get bbox <index>        # Get bounding box (x, y, width, height)
```

### Wait Conditions
```bash
browser-use wait selector "h1"                         # Wait for element
browser-use wait selector ".loading" --state hidden    # Wait for element to disappear
browser-use wait text "Success"                        # Wait for text
browser-use wait selector "#btn" --timeout 5000        # Custom timeout (ms)
```

### Cookies
```bash
browser-use cookies get             # Get all cookies
browser-use cookies get --url <url> # Get cookies for specific URL
browser-use cookies set <name> <val>  # Set a cookie
browser-use cookies set name val --domain .example.com --secure  # With options
browser-use cookies set name val --same-site Strict  # SameSite: Strict, Lax, None
browser-use cookies set name val --expires 1735689600  # Expiration timestamp
browser-use cookies clear           # Clear all cookies
browser-use cookies clear --url <url>  # Clear cookies for specific URL
browser-use cookies export <file>   # Export to JSON
browser-use cookies import <file>   # Import from JSON
```

### Tab Management
```bash
browser-use switch <tab>            # Switch tab by index
browser-use close-tab               # Close current tab
browser-use close-tab <tab>         # Close specific tab
```

### Python Execution (Persistent Session)
```bash
browser-use python "x = 42"           # Set variable
browser-use python "print(x)"         # Access variable (prints: 42)
browser-use python "print(browser.url)"  # Access browser object
browser-use python --vars             # Show defined variables
browser-use python --reset            # Clear namespace
browser-use python --file script.py   # Run Python file
```

The Python session maintains state across commands. The `browser` object provides:
- `browser.url` - Current page URL
- `browser.title` - Page title
- `browser.html` - Get page HTML
- `browser.goto(url)` - Navigate
- `browser.click(index)` - Click element
- `browser.type(text)` - Type text
- `browser.input(index, text)` - Click element, then type
- `browser.keys(keys)` - Send keyboard keys
- `browser.screenshot(path)` - Take screenshot
- `browser.scroll(direction, amount)` - Scroll page
- `browser.back()` - Go back in history
- `browser.wait(seconds)` - Sleep/pause execution
- `browser.extract(query)` - Extract data using LLM

### Agent Tasks
```bash
browser-use run "Fill the contact form with test data"   # AI agent
browser-use run "Extract all product prices" --max-steps 50

# Specify LLM model
browser-use run "task" --llm gpt-4o
browser-use run "task" --llm claude-sonnet-4-20250514
browser-use run "task" --llm gemini-2.0-flash

# Proxy configuration (default: us)
browser-use run "task" --proxy-country gb    # UK proxy
browser-use run "task" --proxy-country de    # Germany proxy

# Session reuse (run multiple tasks in same browser session)
browser-use run "task 1" --keep-alive
# Returns: session_id: abc-123
browser-use run "task 2" --session-id abc-123

# Execution modes
browser-use run "task" --no-wait     # Async, returns task_id immediately
browser-use run "task" --wait        # Wait for completion
browser-use run "task" --stream      # Stream status updates
browser-use run "task" --flash       # Fast execution mode

# Advanced options
browser-use run "task" --thinking    # Extended reasoning mode
browser-use run "task" --vision      # Enable vision (default)
browser-use run "task" --no-vision   # Disable vision

# Use cloud profile (preserves cookies across sessions)
browser-use run "task" --profile <cloud-profile-id>

# Task configuration
browser-use run "task" --start-url https://example.com  # Start from specific URL
browser-use run "task" --allowed-domain example.com     # Restrict navigation (repeatable)
browser-use run "task" --metadata key=value             # Task metadata (repeatable)
browser-use run "task" --secret API_KEY=xxx             # Task secrets (repeatable)
browser-use run "task" --skill-id skill-123             # Enable skills (repeatable)

# Structured output and evaluation
browser-use run "task" --structured-output '{"type":"object"}'  # JSON schema for output
browser-use run "task" --judge                          # Enable judge mode
browser-use run "task" --judge-ground-truth "answer"    # Expected answer for judge
```

### Task Management

Manage cloud tasks:

```bash
browser-use task list                     # List recent tasks
browser-use task list --limit 20          # Show more tasks
browser-use task list --status running    # Filter by status
browser-use task list --status finished
browser-use task list --session <id>      # Filter by session ID
browser-use task list --json              # JSON output

browser-use task status <task-id>         # Get task status (latest step only)
browser-use task status <task-id> -c      # Compact: all steps with reasoning
browser-use task status <task-id> -v      # Verbose: full details with URLs + actions
browser-use task status <task-id> --last 5   # Show only last 5 steps
browser-use task status <task-id> --step 3   # Show specific step number
browser-use task status <task-id> --reverse  # Show steps newest first
browser-use task status <task-id> --json

browser-use task stop <task-id>           # Stop a running task

browser-use task logs <task-id>           # Get task execution logs
```

### Cloud Session Management

Manage cloud browser sessions:

```bash
browser-use session list                  # List cloud sessions
browser-use session list --limit 20       # Show more sessions
browser-use session list --status active  # Filter by status
browser-use session list --json           # JSON output

browser-use session get <session-id>      # Get session details + live URL
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

### Cloud Profile Management

Cloud profiles store browser state (cookies) persistently across sessions. Use profiles to maintain login sessions.

```bash
browser-use profile list                  # List cloud profiles
browser-use profile list --page 2 --page-size 50  # Pagination
browser-use profile get <id>              # Get profile details
browser-use profile create                # Create new profile
browser-use profile create --name "My Profile"  # Create with name
browser-use profile update <id> --name "New Name"  # Rename profile
browser-use profile delete <id>           # Delete profile
```

**Using profiles:**
```bash
# Run task with profile (preserves cookies)
browser-use run "Log into site" --profile <profile-id> --keep-alive

# Create session with profile
browser-use session create --profile <profile-id>

# Open URL with profile
browser-use open https://example.com --profile <profile-id>
```

**Import cookies to cloud profile:**
```bash
# Export cookies from current session
browser-use cookies export /tmp/cookies.json

# Import to cloud profile
browser-use cookies import /tmp/cookies.json --profile <profile-id>
```

## Running Subagents

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
browser-use run "Search for AI news and summarize top 3 articles" --no-wait
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
browser-use run "Research competitor A pricing" --no-wait
# → task_id: task-1, session_id: sess-a

browser-use run "Research competitor B pricing" --no-wait
# → task_id: task-2, session_id: sess-b

browser-use run "Research competitor C pricing" --no-wait
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
browser-use run "Log into example.com" --keep-alive --no-wait
# → task_id: task-1, session_id: sess-123

# Wait for login to complete...
browser-use task status task-1
# → Status: finished

# Give the same agent another task (reuses login session)
browser-use run "Navigate to settings and export data" --session-id sess-123 --no-wait
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
browser-use run "task" --no-wait

# Explicit configuration
browser-use run "task" \
  --llm gpt-4o \
  --proxy-country gb \
  --keep-alive \
  --no-wait

# With cloud profile (preserves cookies across sessions)
browser-use run "task" --profile <profile-id> --no-wait
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
browser-use run "task" --no-wait
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

### Troubleshooting

**Session reuse fails after `task stop`**:
If you stop a task and try to reuse its session, the new task may get stuck at "created" status. Solution: create a new agent instead.
```bash
# This may fail:
browser-use task stop <task-id>
browser-use run "new task" --session-id <same-session>  # Might get stuck

# Do this instead:
browser-use run "new task" --profile <profile-id>  # Fresh session
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
browser-use sessions                # List active sessions
browser-use close                   # Close current session
browser-use close --all             # Close all sessions
```

### Global Options

| Option | Description |
|--------|-------------|
| `--session NAME` | Named session (default: "default") |
| `--browser MODE` | Browser mode (only if multiple modes installed) |
| `--profile ID` | Cloud profile ID for persistent cookies |
| `--json` | Output as JSON |
| `--api-key KEY` | Override API key |

## Common Patterns

### Test a Local Dev Server with Cloud Browser

```bash
# Start dev server
npm run dev &  # localhost:3000

# Tunnel it
browser-use tunnel 3000
# → url: https://abc.trycloudflare.com

# Browse with cloud browser
browser-use open https://abc.trycloudflare.com
browser-use state
browser-use screenshot
```

### Form Submission

```bash
browser-use open https://example.com/contact
browser-use state
# Shows: [0] input "Name", [1] input "Email", [2] textarea "Message", [3] button "Submit"
browser-use input 0 "John Doe"
browser-use input 1 "john@example.com"
browser-use input 2 "Hello, this is a test message."
browser-use click 3
browser-use state   # Verify success
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

1. **Install with `--remote-only`** for sandboxed environments — no `--browser` flag needed
2. **Always run `state` first** to see available elements and their indices
3. **Sessions persist** across commands — the browser stays open until you close it
4. **Tunnels are independent** — they don't require or create a browser session, and persist across `browser-use close`
5. **Use `--json`** for programmatic parsing
6. **`tunnel` is idempotent** — calling it again for the same port returns the existing URL
7. **Close when done** — `browser-use close` closes the browser; `browser-use tunnel stop --all` stops tunnels

## Troubleshooting

**"Browser mode 'chromium' not installed"?**
- You installed with `--remote-only` which doesn't include local modes
- This is expected behavior for sandboxed agents
- If you need local browser, reinstall with `--full`

**Cloud browser won't start?**
- Verify `BROWSER_USE_API_KEY` is set
- Check your API key at https://browser-use.com

**Tunnel not working?**
- Verify cloudflared is installed: `which cloudflared`
- If missing, install manually (see Setup section) or re-run `install.sh --remote-only`
- `browser-use tunnel list` to check active tunnels
- `browser-use tunnel stop <port>` and retry

**Element not found?**
- Run `browser-use state` to see current elements
- `browser-use scroll down` then `browser-use state` — element might be below fold
- Page may have changed — re-run `state` to get fresh indices

## Cleanup

**Close the browser when done:**

```bash
browser-use close              # Close browser session
browser-use tunnel stop --all  # Stop all tunnels (if any)
```

Browser sessions and tunnels are managed separately, so close each as needed.
