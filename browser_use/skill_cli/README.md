# Browser-Use CLI

Fast, persistent browser automation from the command line.

## Installation

### Prerequisites

| Platform | Requirements |
|----------|-------------|
| **macOS** | Python 3.11+ (installer will use Homebrew if needed) |
| **Linux** | Python 3.11+ (installer will use apt if needed) |
| **Windows** | [Git for Windows](https://git-scm.com/download/win), Python 3.11+ |

### One-Line Install (Recommended)

**macOS / Linux:**
```bash
curl -fsSL https://browser-use.com/cli/install.sh | bash
```

**Windows** (run in PowerShell):
```powershell
& "C:\Program Files\Git\bin\bash.exe" -c 'curl -fsSL https://browser-use.com/cli/install.sh | bash'
```

### Installation Modes
```bash
curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --full        # All modes
curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --local-only  # Local browser only
curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --remote-only # Cloud browser only
curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --api-key bu_xxx  # With API key
```

### Post-Install
```bash
browser-use doctor   # Validate installation
browser-use setup    # Run setup wizard (optional)
browser-use setup --mode local|remote|full  # Non-interactive setup
browser-use setup --api-key bu_xxx --yes    # With API key, skip prompts
```

### Generate Templates
```bash
browser-use init                          # Interactive template selection
browser-use init --list                   # List available templates
browser-use init --template basic         # Generate specific template
browser-use init --output my_script.py    # Specify output file
browser-use init --force                  # Overwrite existing files
```

### From Source
```bash
uv pip install -e .
```

### Manual Installation

If you prefer not to use the one-line installer:

```bash
# 1. Install the package
uv pip install browser-use

# 2. Install Chromium (for local browser mode)
browser-use install

# 3. Configure API key (for remote mode)
export BROWSER_USE_API_KEY=your_key  # or $env:BROWSER_USE_API_KEY on Windows

# 4. Validate
browser-use doctor
```

## Quick Start

```bash
# Open a webpage (starts browser automatically)
browser-use open https://example.com

# See clickable elements with their indices
browser-use state

# Click an element by index
browser-use click 5

# Type text into focused element
browser-use type "Hello World"

# Fill a specific input field (click + type)
browser-use input 3 "john@example.com"

# Take a screenshot
browser-use screenshot output.png

# Close the browser
browser-use close
```

## Browser Modes

```bash
# Default: headless Chromium
browser-use open https://example.com

# Visible browser window
browser-use --headed open https://example.com

# Use your real Chrome (with existing logins/cookies)
browser-use --browser real open https://gmail.com

# Cloud browser (requires BROWSER_USE_API_KEY)
browser-use --browser remote open https://example.com
```

## All Commands

### Navigation
| Command | Description |
|---------|-------------|
| `open <url>` | Navigate to URL |
| `back` | Go back in history |
| `scroll down` | Scroll down |
| `scroll up` | Scroll up |
| `scroll down --amount 1000` | Scroll by pixels |

### Inspection
| Command | Description |
|---------|-------------|
| `state` | Get URL, title, and clickable elements |
| `screenshot [path]` | Take screenshot (base64 if no path) |
| `screenshot --full path.png` | Full page screenshot |

### Interaction
| Command | Description |
|---------|-------------|
| `click <index>` | Click element by index |
| `type "text"` | Type into focused element |
| `input <index> "text"` | Click element, then type |
| `keys "Enter"` | Send keyboard keys |
| `keys "Control+a"` | Send key combination |
| `select <index> "value"` | Select dropdown option |
| `hover <index>` | Hover over element |
| `dblclick <index>` | Double-click element |
| `rightclick <index>` | Right-click element |

### Tabs
| Command | Description |
|---------|-------------|
| `switch <tab>` | Switch to tab by index |
| `close-tab` | Close current tab |
| `close-tab <tab>` | Close specific tab |

### Cookies
| Command | Description |
|---------|-------------|
| `cookies get` | Get all cookies |
| `cookies get --url <url>` | Get cookies for URL |
| `cookies set <name> <value>` | Set a cookie |
| `cookies set name val --domain .example.com --secure` | Set with options |
| `cookies set name val --same-site Strict` | SameSite: Strict, Lax, None |
| `cookies set name val --expires 1735689600` | Set expiration timestamp |
| `cookies clear` | Clear all cookies |
| `cookies clear --url <url>` | Clear cookies for URL |
| `cookies export <file>` | Export to JSON file |
| `cookies import <file>` | Import from JSON file |

### Wait
| Command | Description |
|---------|-------------|
| `wait selector "css"` | Wait for element to be visible |
| `wait selector ".loading" --state hidden` | Wait for element to disappear |
| `wait text "Success"` | Wait for text to appear |
| `wait selector "h1" --timeout 5000` | Custom timeout (ms) |

### Get (Information Retrieval)
| Command | Description |
|---------|-------------|
| `get title` | Get page title |
| `get html` | Get full page HTML |
| `get html --selector "h1"` | Get HTML of element |
| `get text <index>` | Get text content of element |
| `get value <index>` | Get value of input/textarea |
| `get attributes <index>` | Get all attributes of element |
| `get bbox <index>` | Get bounding box (x, y, width, height) |

### JavaScript & Data
| Command | Description |
|---------|-------------|
| `eval "js code"` | Execute JavaScript |
| `extract "query"` | Extract data with LLM |

### Python (Persistent Session)
```bash
browser-use python "x = 42"           # Set variable
browser-use python "print(x)"         # Access variable (prints: 42)
browser-use python "print(browser.url)"  # Access browser
browser-use python --vars             # Show defined variables
browser-use python --reset            # Clear namespace
browser-use python --file script.py   # Run Python file
```

## Agent Tasks

Run AI-powered browser automation tasks.

### Local Mode
```bash
browser-use run "Fill the contact form with test data"
browser-use run "Extract all product prices" --max-steps 50
browser-use run "task" --llm gpt-4o   # Specify LLM model
```

Requires an LLM API key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.).

### Remote Mode (Cloud)
```bash
browser-use -b remote run "Search for AI news"              # US proxy default
browser-use -b remote run "task" --llm gpt-4o               # Specify LLM
browser-use -b remote run "task" --proxy-country gb         # UK proxy
browser-use -b remote run "task" --session-id <id>          # Reuse session
browser-use -b remote run "task" --no-wait                  # Async (returns task ID)
browser-use -b remote run "task" --wait                     # Wait for completion
browser-use -b remote run "task" --stream                   # Stream output
browser-use -b remote run "task" --flash                    # Fast mode
browser-use -b remote run "task" --keep-alive               # Keep session alive
browser-use -b remote run "task" --thinking                 # Extended reasoning
browser-use -b remote run "task" --vision                   # Enable vision (default)
browser-use -b remote run "task" --no-vision                # Disable vision
browser-use -b remote run "task" --profile <id>             # Use cloud profile

# Task configuration
browser-use -b remote run "task" --start-url https://example.com  # Start from URL
browser-use -b remote run "task" --allowed-domain example.com     # Restrict navigation (repeatable)
browser-use -b remote run "task" --metadata key=value             # Task metadata (repeatable)
browser-use -b remote run "task" --secret API_KEY=xxx             # Task secrets (repeatable)
browser-use -b remote run "task" --skill-id skill-123             # Enable skills (repeatable)

# Structured output and evaluation
browser-use -b remote run "task" --structured-output '{"type":"object"}'  # JSON schema
browser-use -b remote run "task" --judge                          # Enable judge mode
browser-use -b remote run "task" --judge-ground-truth "answer"    # Expected answer
```

Requires `BROWSER_USE_API_KEY`.

## Task Management (Remote Mode)

Manage cloud tasks when using `--browser remote`.

| Command | Description |
|---------|-------------|
| `task list` | List recent tasks |
| `task list --status running` | Filter by status |
| `task list --session <id>` | Filter by session ID |
| `task status <id>` | Get task status (latest step only) |
| `task status <id> -c` | Compact: all steps with reasoning |
| `task status <id> -v` | Verbose: full details |
| `task status <id> --last 5` | Show last 5 steps |
| `task status <id> --step 3` | Show specific step number |
| `task status <id> --reverse` | Show steps newest first |
| `task stop <id>` | Stop running task |
| `task logs <id>` | Get execution logs |

## Cloud Sessions (Remote Mode)

Manage cloud browser sessions.

| Command | Description |
|---------|-------------|
| `session list` | List cloud sessions |
| `session list --status active` | Filter by status |
| `session get <id>` | Get session details + live URL |
| `session stop <id>` | Stop session |
| `session stop --all` | Stop all active sessions |
| `session create` | Create new session |
| `session create --profile <id>` | With cloud profile |
| `session create --proxy-country gb` | With geographic proxy |
| `session create --start-url <url>` | Start at specific URL |
| `session create --screen-size 1920x1080` | Custom screen size |
| `session create --keep-alive` | Keep session alive |
| `session create --persist-memory` | Persist memory between tasks |
| `session share <id>` | Create public share URL |
| `session share <id> --delete` | Delete public share |

## Tunnels

Expose local dev servers to cloud browsers via Cloudflare tunnels.

| Command | Description |
|---------|-------------|
| `tunnel <port>` | Start tunnel, get public URL |
| `tunnel list` | List active tunnels |
| `tunnel stop <port>` | Stop tunnel for port |
| `tunnel stop --all` | Stop all tunnels |

```bash
# Example: Test local dev server with cloud browser
npm run dev &                              # localhost:3000
browser-use tunnel 3000                    # → https://abc.trycloudflare.com
browser-use -b remote open https://abc.trycloudflare.com
```

## Profile Management

### Local Profiles (`-b real`)
| Command | Description |
|---------|-------------|
| `profile list` | List Chrome profiles |
| `profile cookies <name>` | Show cookies by domain |
| `profile sync --from <name>` | Sync local profile to cloud |
| `profile sync --from Default --domain youtube.com` | Sync specific domain only |

### Cloud Profiles (`-b remote`)
| Command | Description |
|---------|-------------|
| `profile list` | List cloud profiles |
| `profile list --page 2 --page-size 50` | Pagination |
| `profile get <id>` | Get profile details |
| `profile create` | Create profile |
| `profile create --name "My Profile"` | Create with name |
| `profile update <id> --name <name>` | Rename profile |
| `profile delete <id>` | Delete profile |

## Local Session Management

| Command | Description |
|---------|-------------|
| `sessions` | List active sessions |
| `close` | Close browser session |
| `close --all` | Close all sessions |
| `server status` | Check if server is running |
| `server stop` | Stop server |
| `server logs` | View server logs |

## Global Options

| Option | Description |
|--------|-------------|
| `--session NAME` | Use named session (default: "default") |
| `--browser MODE` | Browser mode: chromium, real, remote |
| `--headed` | Show browser window |
| `--profile NAME` | Browser profile (local name or cloud ID) |
| `--json` | Output as JSON |
| `--api-key KEY` | Override API key |
| `--mcp` | Run as MCP server via stdin/stdout |

**Session behavior**: All commands without `--session` use the same "default" session. The browser stays open and is reused across commands. Use `--session NAME` to run multiple browsers in parallel.

## Examples

### Fill a Form
```bash
browser-use open https://example.com/contact
browser-use state
# Shows: [0] input "Name", [1] input "Email", [2] button "Submit"
browser-use input 0 "John Doe"
browser-use input 1 "john@example.com"
browser-use click 2
```

### Extract Data with JavaScript
```bash
browser-use open https://news.ycombinator.com
browser-use eval "Array.from(document.querySelectorAll('.titleline a')).slice(0,5).map(a => a.textContent)"
```

### Multi-Session Workflow
```bash
browser-use --session work open https://work.example.com
browser-use --session personal open https://personal.example.com
browser-use --session work state
browser-use --session personal state
browser-use close --all
```

### Python Automation
```bash
browser-use open https://example.com
browser-use python "
for i in range(5):
    browser.scroll('down')
    browser.wait(0.5)
browser.screenshot('scrolled.png')
"
```

### Cloud Agent with Session Reuse
```bash
# Start task, keep session alive
browser-use -b remote run "Log into example.com" --keep-alive --no-wait
# → task_id: task-123, session_id: sess-456

# Check task status
browser-use task status task-123

# Run another task in same session (preserves login)
browser-use -b remote run "Go to settings" --session-id sess-456
```

## Claude Code Skill

For [Claude Code](https://claude.ai/code), a skill provides richer context for browser automation:

```bash
mkdir -p ~/.claude/skills/browser-use
curl -o ~/.claude/skills/browser-use/SKILL.md \
  https://raw.githubusercontent.com/browser-use/browser-use/main/skills/browser-use/SKILL.md
```

## How It Works

The CLI uses a session server architecture:

1. First command starts a background server (browser stays open)
2. Subsequent commands communicate via Unix socket (or TCP on Windows)
3. Browser persists across commands for fast interaction
4. Server auto-starts when needed, stops with `browser-use server stop`

This gives you ~50ms command latency instead of waiting for browser startup each time.

<details>
<summary>Windows Troubleshooting</summary>

### ARM64 Windows (Surface Pro X, Snapdragon laptops)
Install x64 Python (runs via emulation):
```powershell
winget install Python.Python.3.11 --architecture x64
```

### Multiple Python versions
Set the version explicitly:
```powershell
$env:PY_PYTHON=3.11
```

### PATH not working after install
Restart your terminal. If still not working:
```powershell
# Check PATH
echo $env:PATH

# Or run via Git Bash
& "C:\Program Files\Git\bin\bash.exe" -c 'browser-use --help'
```

### "Failed to start session server" error
Kill zombie processes:
```powershell
# Find process on port
netstat -ano | findstr 49698

# Kill by PID
taskkill /PID <pid> /F

# Or kill all Python
taskkill /IM python.exe /F
```

### Stale virtual environment
Delete and reinstall:
```powershell
taskkill /IM python.exe /F
Remove-Item -Recurse -Force "$env:USERPROFILE\.browser-use-env"
# Then run installer again
```

</details>
