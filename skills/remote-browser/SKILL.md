---
name: remote-browser
description: Controls a cloud browser from a sandboxed remote machine. Use when the agent is running in a sandbox (no GUI) and needs to navigate websites, interact with web pages, fill forms, take screenshots, or expose local dev servers via tunnels.
allowed-tools: Bash(browser-use:*)
---

# Remote Browser Automation for Sandboxed Agents

This skill is for agents running on **sandboxed remote machines** (cloud VMs, CI, coding agents) that need to control a browser. Install `browser-use` and drive a cloud browser — no local Chrome needed.

## Prerequisites

Before using this skill, `browser-use` must be installed and configured. Run diagnostics to verify:

```bash
browser-use doctor
```

For more information, see https://github.com/browser-use/browser-use/blob/main/browser_use/skill_cli/README.md

## Core Workflow

Commands use the cloud browser:

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

## Essential Commands

```bash
# Navigation
browser-use open <url>                    # Navigate to URL
browser-use back                          # Go back
browser-use scroll down                   # Scroll down (--amount N for pixels)

# Page State (always run state first to get element indices)
browser-use state                         # Get URL, title, clickable elements
browser-use screenshot                    # Take screenshot (base64)
browser-use screenshot path.png           # Save screenshot to file

# Interactions (use indices from state)
browser-use click <index>                 # Click element
browser-use type "text"                   # Type into focused element
browser-use input <index> "text"          # Click element, then type
browser-use keys "Enter"                  # Send keyboard keys
browser-use select <index> "option"       # Select dropdown option

# Data Extraction
browser-use eval "document.title"         # Execute JavaScript
browser-use get text <index>              # Get element text
browser-use get html --selector "h1"      # Get scoped HTML

# Wait
browser-use wait selector "h1"            # Wait for element
browser-use wait text "Success"           # Wait for text

# Session
browser-use close                         # Close browser session

# AI Agent
browser-use run "task"                    # Run agent (async by default)
browser-use task status <id>              # Check task progress
```

## Commands

### Navigation & Tabs
```bash
browser-use open <url>              # Navigate to URL
browser-use back                    # Go back in history
browser-use scroll down             # Scroll down
browser-use scroll up               # Scroll up
browser-use scroll down --amount 1000  # Scroll by specific pixels (default: 500)
browser-use switch <tab>            # Switch tab by index
browser-use close-tab               # Close current tab
browser-use close-tab <tab>         # Close specific tab
```

### Page State
```bash
browser-use state                   # Get URL, title, and clickable elements
browser-use screenshot              # Take screenshot (base64)
browser-use screenshot path.png     # Save screenshot to file
browser-use screenshot --full p.png # Full page screenshot
```

### Interactions
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

Use indices from `browser-use state`.

### JavaScript & Data
```bash
browser-use eval "document.title"   # Execute JavaScript
browser-use get title               # Get page title
browser-use get html                # Get page HTML
browser-use get html --selector "h1"  # Scoped HTML
browser-use get text <index>        # Get element text
browser-use get value <index>       # Get input value
browser-use get attributes <index>  # Get element attributes
browser-use get bbox <index>        # Get bounding box (x, y, width, height)
```

### Cookies
```bash
browser-use cookies get             # Get all cookies
browser-use cookies get --url <url> # Get cookies for specific URL
browser-use cookies set <name> <val>  # Set a cookie
browser-use cookies set name val --domain .example.com --secure
browser-use cookies set name val --same-site Strict  # SameSite: Strict, Lax, None
browser-use cookies set name val --expires 1735689600  # Expiration timestamp
browser-use cookies clear           # Clear all cookies
browser-use cookies clear --url <url>  # Clear cookies for specific URL
browser-use cookies export <file>   # Export to JSON
browser-use cookies import <file>   # Import from JSON
```

### Wait Conditions
```bash
browser-use wait selector "h1"                         # Wait for element
browser-use wait selector ".loading" --state hidden    # Wait for element to disappear
browser-use wait text "Success"                        # Wait for text
browser-use wait selector "#btn" --timeout 5000        # Custom timeout (ms)
```

### Python Execution
```bash
browser-use python "x = 42"           # Set variable
browser-use python "print(x)"         # Access variable (prints: 42)
browser-use python "print(browser.url)"  # Access browser object
browser-use python --vars             # Show defined variables
browser-use python --reset            # Clear namespace
browser-use python --file script.py   # Run Python file
```

The Python session maintains state across commands. The `browser` object provides:
- `browser.url`, `browser.title`, `browser.html` — page info
- `browser.goto(url)`, `browser.back()` — navigation
- `browser.click(index)`, `browser.type(text)`, `browser.input(index, text)`, `browser.keys(keys)` — interactions
- `browser.screenshot(path)`, `browser.scroll(direction, amount)` — visual
- `browser.wait(seconds)`, `browser.extract(query)` — utilities

### Agent Tasks
```bash
browser-use run "Fill the contact form with test data"   # AI agent
browser-use run "Extract all product prices" --max-steps 50

# Specify LLM model
browser-use run "task" --llm gpt-4o
browser-use run "task" --llm claude-sonnet-4-20250514

# Proxy configuration (default: us)
browser-use run "task" --proxy-country uk

# Session reuse
browser-use run "task 1" --keep-alive        # Keep session alive after task
browser-use run "task 2" --session-id abc-123 # Reuse existing session

# Execution modes
browser-use run "task" --flash       # Fast execution mode
browser-use run "task" --wait        # Wait for completion (default: async)

# Advanced options
browser-use run "task" --thinking    # Extended reasoning mode
browser-use run "task" --no-vision   # Disable vision (enabled by default)

# Using a cloud profile (create session first, then run with --session-id)
browser-use session create --profile <cloud-profile-id> --keep-alive
# → returns session_id
browser-use run "task" --session-id <session-id>

# Task configuration
browser-use run "task" --start-url https://example.com  # Start from specific URL
browser-use run "task" --allowed-domain example.com     # Restrict navigation (repeatable)
browser-use run "task" --metadata key=value             # Task metadata (repeatable)
browser-use run "task" --skill-id skill-123             # Enable skills (repeatable)
browser-use run "task" --secret key=value               # Secret metadata (repeatable)

# Structured output and evaluation
browser-use run "task" --structured-output '{"type":"object"}'  # JSON schema for output
browser-use run "task" --judge                          # Enable judge mode
browser-use run "task" --judge-ground-truth "answer"
```

### Task Management
```bash
browser-use task list                     # List recent tasks
browser-use task list --limit 20          # Show more tasks
browser-use task list --status finished   # Filter by status (finished, stopped)
browser-use task list --session <id>      # Filter by session ID
browser-use task list --json              # JSON output

browser-use task status <task-id>         # Get task status (latest step only)
browser-use task status <task-id> -c      # All steps with reasoning
browser-use task status <task-id> -v      # All steps with URLs + actions
browser-use task status <task-id> --last 5  # Last N steps only
browser-use task status <task-id> --step 3  # Specific step number
browser-use task status <task-id> --reverse # Newest first

browser-use task stop <task-id>           # Stop a running task
browser-use task logs <task-id>           # Get task execution logs
```

### Cloud Session Management
```bash
browser-use session list                  # List cloud sessions
browser-use session list --limit 20       # Show more sessions
browser-use session list --status active  # Filter by status
browser-use session list --json           # JSON output

browser-use session get <session-id>      # Get session details + live URL
browser-use session get <session-id> --json

browser-use session stop <session-id>     # Stop a session
browser-use session stop --all            # Stop all active sessions

browser-use session create                          # Create with defaults
browser-use session create --profile <id>           # With cloud profile
browser-use session create --proxy-country uk       # With geographic proxy
browser-use session create --start-url https://example.com
browser-use session create --screen-size 1920x1080
browser-use session create --keep-alive
browser-use session create --persist-memory

browser-use session share <session-id>              # Create public share URL
browser-use session share <session-id> --delete     # Delete public share
```

### Cloud Profile Management
```bash
browser-use profile list                  # List cloud profiles
browser-use profile list --page 2 --page-size 50
browser-use profile get <id>              # Get profile details
browser-use profile create                # Create new profile
browser-use profile create --name "My Profile"
browser-use profile update <id> --name "New Name"
browser-use profile delete <id>
```

### Tunnels
```bash
browser-use tunnel <port>           # Start tunnel (returns URL)
browser-use tunnel <port>           # Idempotent - returns existing URL
browser-use tunnel list             # Show active tunnels
browser-use tunnel stop <port>      # Stop tunnel
browser-use tunnel stop --all       # Stop all tunnels
```

### Session Management
```bash
browser-use sessions                # List active sessions
browser-use close                   # Close current session
browser-use close --all             # Close all sessions
```

## Common Workflows

### Exposing Local Dev Servers

Use when you have a dev server on the remote machine and need the cloud browser to reach it.

**Core workflow:** Start dev server → create tunnel → browse the tunnel URL.

```bash
# 1. Start your dev server
python -m http.server 3000 &

# 2. Expose it via Cloudflare tunnel
browser-use tunnel 3000
# → url: https://abc.trycloudflare.com

# 3. Now the cloud browser can reach your local server
browser-use open https://abc.trycloudflare.com
browser-use state
browser-use screenshot
```

**Note:** Tunnels are independent of browser sessions. They persist across `browser-use close` and can be managed separately. Cloudflared must be installed — run `browser-use doctor` to check.

### Running Subagents

Use cloud sessions to run autonomous browser agents in parallel.

**Core workflow:** Launch task(s) with `run` → poll with `task status` → collect results → clean up sessions.

- **Session = Agent**: Each cloud session is a browser agent with its own state
- **Task = Work**: Jobs given to an agent; an agent can run multiple tasks sequentially
- **Session lifecycle**: Once stopped, a session cannot be revived — start a new one

#### Launching Tasks

```bash
# Single task (async by default — returns immediately)
browser-use run "Search for AI news and summarize top 3 articles"
# → task_id: task-abc, session_id: sess-123

# Parallel tasks — each gets its own session
browser-use run "Research competitor A pricing"
# → task_id: task-1, session_id: sess-a
browser-use run "Research competitor B pricing"
# → task_id: task-2, session_id: sess-b
browser-use run "Research competitor C pricing"
# → task_id: task-3, session_id: sess-c

# Sequential tasks in same session (reuses cookies, login state, etc.)
browser-use run "Log into example.com" --keep-alive
# → task_id: task-1, session_id: sess-123
browser-use task status task-1  # Wait for completion
browser-use run "Export settings" --session-id sess-123
# → task_id: task-2, session_id: sess-123 (same session)
```

#### Managing & Stopping

```bash
browser-use task list --status finished      # See completed tasks
browser-use task stop task-abc               # Stop a task (session may continue if --keep-alive)
browser-use session stop sess-123            # Stop an entire session (terminates its tasks)
browser-use session stop --all               # Stop all sessions
```

#### Monitoring

**Task status is designed for token efficiency.** Default output is minimal — only expand when needed:

| Mode | Flag | Tokens | Use When |
|------|------|--------|----------|
| Default | (none) | Low | Polling progress |
| Compact | `-c` | Medium | Need full reasoning |
| Verbose | `-v` | High | Debugging actions |

```bash
# For long tasks (50+ steps)
browser-use task status <id> -c --last 5   # Last 5 steps only
browser-use task status <id> -v --step 10  # Inspect specific step
```

**Live view**: `browser-use session get <session-id>` returns a live URL to watch the agent.

**Detect stuck tasks**: If cost/duration in `task status` stops increasing, the task is stuck — stop it and start a new agent.

**Logs**: `browser-use task logs <task-id>` — only available after task completes.

## Global Options

| Option | Description |
|--------|-------------|
| `--session NAME` | Named session (default: "default") |
| `--browser MODE` | Browser mode (only if multiple modes installed) |
| `--profile ID` | Cloud profile ID for persistent cookies. Works with `open`, `session create`, etc. — does NOT work with `run` (use `--session-id` instead) |
| `--json` | Output as JSON |

## Tips

1. **Run `browser-use doctor`** to verify installation before starting
2. **Always run `state` first** to see available elements and their indices
3. **Sessions persist** across commands — the browser stays open until you close it
4. **Tunnels are independent** — they persist across `browser-use close`
5. **Use `--json`** for programmatic parsing
6. **`tunnel` is idempotent** — calling it again for the same port returns the existing URL

## Troubleshooting

**"Browser mode 'chromium' not installed"?**
- Expected for sandboxed agents — remote mode only supports cloud browsers
- Run `browser-use doctor` to verify configuration

**Cloud browser won't start?**
- Run `browser-use doctor` to check configuration

**Tunnel not working?**
- Verify cloudflared is installed: `which cloudflared`
- `browser-use tunnel list` to check active tunnels
- `browser-use tunnel stop <port>` and retry

**Element not found?**
- Run `browser-use state` to see current elements
- `browser-use scroll down` then `browser-use state` — element might be below fold

**Session reuse fails after `task stop`**:
Create a new session instead:
```bash
browser-use session create --profile <profile-id> --keep-alive
browser-use run "new task" --session-id <new-session-id>
```

**Task stuck at "started"**: Check cost with `task status` — if not increasing, the task is stuck. View live URL with `session get`, then stop and start a new agent.

**Sessions persist after tasks complete**: Run `browser-use session stop --all` to clean up.

## Cleanup

**Always close resources when done:**

```bash
browser-use close                     # Close browser session
browser-use session stop --all        # Stop cloud sessions (if any)
browser-use tunnel stop --all         # Stop tunnels (if any)
```
