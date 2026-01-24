# Browser-Use CLI

Fast, persistent browser automation from the command line.

## Installation

```bash
# From the browser-use repo directory
uv pip install -e .
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
| `browser-use open <url>` | Navigate to URL |
| `browser-use back` | Go back in history |
| `browser-use scroll down` | Scroll down |
| `browser-use scroll up` | Scroll up |

### Inspection
| Command | Description |
|---------|-------------|
| `browser-use state` | Get URL, title, and clickable elements |
| `browser-use screenshot [path]` | Take screenshot (base64 if no path) |
| `browser-use screenshot --full path.png` | Full page screenshot |

### Interaction
| Command | Description |
|---------|-------------|
| `browser-use click <index>` | Click element by index |
| `browser-use type "text"` | Type into focused element |
| `browser-use input <index> "text"` | Click element, then type |
| `browser-use keys "Enter"` | Send keyboard keys |
| `browser-use keys "Control+a"` | Send key combination |
| `browser-use select <index> "value"` | Select dropdown option |

### Tabs
| Command | Description |
|---------|-------------|
| `browser-use switch <tab>` | Switch to tab by index |
| `browser-use close-tab` | Close current tab |
| `browser-use close-tab <tab>` | Close specific tab |

### JavaScript & Data
| Command | Description |
|---------|-------------|
| `browser-use eval "js code"` | Execute JavaScript |
| `browser-use extract "query"` | Extract data with LLM |

### Python (Persistent Session)
```bash
browser-use python "x = 42"           # Set variable
browser-use python "print(x)"         # Access variable (prints: 42)
browser-use python "print(browser.url)"  # Access browser
browser-use python --vars             # Show defined variables
browser-use python --reset            # Clear namespace
browser-use python --file script.py   # Run Python file
```

### Session Management
| Command | Description |
|---------|-------------|
| `browser-use sessions` | List active sessions |
| `browser-use close` | Close browser session |
| `browser-use close --all` | Close all sessions |
| `browser-use server status` | Check if server is running |
| `browser-use server stop` | Stop server |

## Global Options

| Option | Description |
|--------|-------------|
| `--session NAME` | Use named session (default: "default") |
| `--browser MODE` | Browser mode: chromium, real, remote |
| `--headed` | Show browser window |
| `--profile NAME` | Chrome profile (real mode) |
| `--json` | Output as JSON |
| `--api-key KEY` | Override API key |

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
2. Subsequent commands communicate via Unix socket
3. Browser persists across commands for fast interaction
4. Server auto-starts when needed, stops with `browser-use server stop`

This gives you ~50ms command latency instead of waiting for browser startup each time.
