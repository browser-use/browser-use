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

### Post-Install
```bash
browser-use doctor   # Validate installation
browser-use setup    # Run setup wizard (optional)
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

# 2. Install Chromium
browser-use install

# 3. Validate
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

# Use your real Chrome with Default profile (with existing logins/cookies)
browser-use --profile "Default" open https://gmail.com

# Use a specific Chrome profile
browser-use --profile "Profile 1" open https://gmail.com

# Auto-discover and connect to running Chrome
browser-use --connect open https://example.com

# Connect to an existing browser via CDP URL
browser-use --cdp-url http://localhost:9222 open https://example.com

# WebSocket CDP URL also works
browser-use --cdp-url ws://localhost:9222/devtools/browser/... state
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
| `click <x> <y>` | Click at pixel coordinates |
| `type "text"` | Type into focused element |
| `input <index> "text"` | Click element, then type |
| `keys "Enter"` | Send keyboard keys |
| `keys "Control+a"` | Send key combination |
| `select <index> "value"` | Select dropdown option |
| `upload <index> <path>` | Upload file to file input element |
| `hover <index>` | Hover over element |
| `dblclick <index>` | Double-click element |
| `rightclick <index>` | Right-click element |

### Tabs
| Command | Description |
|---------|-------------|
| `tab list` | List all tabs |
| `tab new [url]` | Open new tab |
| `tab switch <index>` | Switch to tab by index |
| `tab close [index...]` | Close tab(s) (current if no index) |

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
| `extract "query"` | Extract data with LLM (not yet implemented) |

### Python (Persistent Session)
```bash
browser-use python "x = 42"           # Set variable
browser-use python "print(x)"         # Access variable (prints: 42)
browser-use python "print(browser.url)"  # Access browser
browser-use python --vars             # Show defined variables
browser-use python --reset            # Clear namespace
browser-use python --file script.py   # Run Python file
```

## Cloud API

Generic REST passthrough to the Browser-Use Cloud API, plus cloud browser provisioning.

| Command | Description |
|---------|-------------|
| `cloud connect` | Provision cloud browser and connect (zero-config, auto-manages profile) |
| `cloud login <api-key>` | Save API key |
| `cloud logout` | Remove API key |
| `cloud v2 GET <path>` | GET request to API v2 |
| `cloud v2 POST <path> '<json>'` | POST request to API v2 |
| `cloud v3 POST <path> '<json>'` | POST request to API v3 |
| `cloud v2 poll <task-id>` | Poll task until done |
| `cloud v2 --help` | Show API v2 endpoints (from OpenAPI spec) |
| `cloud v3 --help` | Show API v3 endpoints |

```bash
# Save API key to ~/.browser-use/config.json
browser-use cloud login sk-abc123...

# Provision a cloud browser and connect
browser-use cloud connect
browser-use state                    # works normally
browser-use close                    # disconnects AND stops cloud browser

# List browsers
browser-use cloud v2 GET /browsers

# Create a task
browser-use cloud v2 POST /tasks '{"task":"Search for AI news","url":"https://google.com"}'

# Poll until done
browser-use cloud v2 poll <task-id>

# Remove API key
browser-use cloud logout
```

API key stored in `~/.browser-use/config.json` with `0600` permissions.

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
browser-use cloud connect                  # Provision cloud browser
browser-use open https://abc.trycloudflare.com
```

## Profile Management

The `profile` subcommand delegates to the [profile-use](https://github.com/browser-use/profile-use) Go binary, which syncs local browser cookies to Browser-Use cloud.

The binary is managed at `~/.browser-use/bin/profile-use` and auto-downloaded on first use.

| Command | Description |
|---------|-------------|
| `profile` | Interactive sync wizard |
| `profile list` | List detected browsers and profiles |
| `profile sync --all` | Sync all profiles to cloud |
| `profile sync --browser "Google Chrome" --profile "Default"` | Sync specific profile |
| `profile auth --apikey <key>` | Set API key (shared with `cloud login`) |
| `profile inspect --browser "Google Chrome" --profile "Default"` | Inspect cookies locally |
| `profile update` | Download/update the profile-use binary |

## Session Management

| Command | Description |
|---------|-------------|
| `sessions` | List active browser sessions |
| `close` | Close current session's browser and daemon |
| `close --all` | Close all sessions |
| `--session NAME` | Target a named session (default: "default") |

```bash
# Default behavior unchanged
browser-use open https://example.com           # uses session 'default'
browser-use state                              # talks to 'default' daemon

# Named sessions
browser-use --session work open https://example.com
browser-use --session work state
browser-use --session cloud cloud connect

# List active sessions
browser-use sessions

# Close specific session
browser-use --session work close

# Close all sessions
browser-use close --all

# Env var fallback
BROWSER_USE_SESSION=work browser-use state
```

## Global Options

| Option | Description |
|--------|-------------|
| `--headed` | Show browser window |
| `--profile [NAME]` | Use real Chrome (bare `--profile` uses "Default") |
| `--connect` | Auto-discover and connect to running Chrome via CDP |
| `--cdp-url <url>` | Connect to existing browser via CDP URL (`http://` or `ws://`) |
| `--session NAME` | Target a named session (default: "default", env: `BROWSER_USE_SESSION`) |
| `--json` | Output as JSON |
| `--mcp` | Run as MCP server via stdin/stdout |

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

## Claude Code Skill

For [Claude Code](https://claude.ai/code), a skill provides richer context for browser automation:

```bash
mkdir -p ~/.claude/skills/browser-use
curl -o ~/.claude/skills/browser-use/SKILL.md \
  https://raw.githubusercontent.com/browser-use/browser-use/main/skills/browser-use/SKILL.md
```

## How It Works

The CLI uses a multi-session daemon architecture:

1. First command starts a background daemon for that session (browser stays open)
2. Subsequent commands communicate via Unix socket (or TCP on Windows)
3. Browser persists across commands for fast interaction
4. Each `--session` gets its own daemon, socket, and PID file in `~/.browser-use/`
5. Daemon auto-starts when needed, auto-exits when browser dies, or stops with `browser-use close`

This gives you ~50ms command latency instead of waiting for browser startup each time.

### File Layout

All CLI-managed files live under `~/.browser-use/` (override with `BROWSER_USE_HOME`):

```
~/.browser-use/
├── config.json          # API key, settings (shared with profile-use)
├── bin/
│   └── profile-use      # Managed Go binary (auto-downloaded)
├── tunnels/
│   ├── {port}.json      # Tunnel metadata
│   └── {port}.log       # Tunnel logs
├── default.state.json   # Daemon lifecycle state (phase, PID, config)
├── default.sock         # Daemon socket (ephemeral)
├── default.pid          # Daemon PID (ephemeral)
└── cli.log              # Daemon log
```

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

### "Failed to start daemon" error
Kill zombie processes:
```powershell
# Find browser-use Python processes
tasklist | findstr python

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
