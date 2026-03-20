---
name: browser-use
description: Automates browser interactions for web testing, form filling, screenshots, and data extraction. Use when the user needs to navigate websites, interact with web pages, fill forms, take screenshots, or extract information from web pages.
allowed-tools: Bash(browser-use:*)
---

# Browser Automation with browser-use CLI

The `browser-use` command provides fast, persistent browser automation. A background daemon keeps the browser open across commands, giving ~50ms latency per call.

## Prerequisites

```bash
browser-use doctor    # Verify installation
```

For setup details, see https://github.com/browser-use/browser-use/blob/main/browser_use/skill_cli/README.md

## Core Workflow

1. **Navigate**: `browser-use open <url>` — starts browser if needed
2. **Inspect**: `browser-use state` — returns clickable elements with indices
3. **Interact**: use indices from state (`browser-use click 5`, `browser-use input 3 "text"`)
4. **Verify**: `browser-use state` or `browser-use screenshot` to confirm
5. **Repeat**: browser stays open between commands
6. **Cleanup**: `browser-use close` when done

## Browser Modes

```bash
browser-use open <url>                         # Default: headless Chromium
browser-use --headed open <url>                # Visible window
browser-use --profile "Default" open <url>      # Real Chrome with Default profile (existing logins/cookies)
browser-use --profile "Profile 1" open <url>   # Real Chrome with named profile
browser-use --connect open <url>               # Auto-discover running Chrome via CDP
browser-use --cdp-url ws://localhost:9222/... open <url>  # Connect via CDP URL
```

`--connect`, `--cdp-url`, and `--profile` are mutually exclusive.

## Commands

```bash
# Navigation
browser-use open <url>                    # Navigate to URL
browser-use back                          # Go back in history
browser-use scroll down                   # Scroll down (--amount N for pixels)
browser-use scroll up                     # Scroll up
browser-use switch <tab>                  # Switch to tab by index
browser-use close-tab [tab]              # Close tab (current if no index)

# Page State — always run state first to get element indices
browser-use state                         # URL, title, clickable elements with indices
browser-use screenshot [path.png]         # Screenshot (base64 if no path, --full for full page)

# Interactions — use indices from state
browser-use click <index>                 # Click element by index
browser-use click <x> <y>                 # Click at pixel coordinates
browser-use type "text"                   # Type into focused element
browser-use input <index> "text"          # Click element, then type
browser-use keys "Enter"                  # Send keyboard keys (also "Control+a", etc.)
browser-use select <index> "option"       # Select dropdown option
browser-use upload <index> <path>         # Upload file to file input
browser-use hover <index>                 # Hover over element
browser-use dblclick <index>              # Double-click element
browser-use rightclick <index>            # Right-click element

# Data Extraction
browser-use eval "js code"                # Execute JavaScript, return result
browser-use get title                     # Page title
browser-use get html [--selector "h1"]    # Page HTML (or scoped to selector)
browser-use get text <index>              # Element text content
browser-use get value <index>             # Input/textarea value
browser-use get attributes <index>        # Element attributes
browser-use get bbox <index>              # Bounding box (x, y, width, height)

# Wait
browser-use wait selector "css"           # Wait for element (--state visible|hidden|attached|detached, --timeout ms)
browser-use wait text "text"              # Wait for text to appear

# Cookies
browser-use cookies get [--url <url>]     # Get cookies (optionally filtered)
browser-use cookies set <name> <value>    # Set cookie (--domain, --secure, --http-only, --same-site, --expires)
browser-use cookies clear [--url <url>]   # Clear cookies
browser-use cookies export <file>         # Export to JSON
browser-use cookies import <file>         # Import from JSON

# Python — persistent session with browser access
browser-use python "code"                 # Execute Python (variables persist across calls)
browser-use python --file script.py       # Run file
browser-use python --vars                 # Show defined variables
browser-use python --reset                # Clear namespace

# Session
browser-use close                         # Close browser and stop daemon
browser-use sessions                      # List active sessions
browser-use close --all                   # Close all sessions
```

The Python `browser` object provides: `browser.url`, `browser.title`, `browser.html`, `browser.goto(url)`, `browser.back()`, `browser.click(index)`, `browser.type(text)`, `browser.input(index, text)`, `browser.keys(keys)`, `browser.upload(index, path)`, `browser.screenshot(path)`, `browser.scroll(direction, amount)`, `browser.wait(seconds)`.

## Cloud API

```bash
browser-use cloud connect                 # Provision cloud browser and connect
browser-use cloud connect --timeout 120 --proxy-country US  # With options
browser-use cloud login <api-key>         # Save API key (or set BROWSER_USE_API_KEY)
browser-use cloud logout                  # Remove API key
browser-use cloud v2 GET /browsers        # REST passthrough (v2 or v3)
browser-use cloud v2 POST /tasks '{"task":"...","url":"..."}'
browser-use cloud v2 poll <task-id>       # Poll task until done
browser-use cloud v2 --help               # Show API endpoints
```

`cloud connect` provisions a cloud browser, connects via CDP, and prints a live URL. `browser-use close` disconnects AND stops the cloud browser.

## Tunnels

```bash
browser-use tunnel <port>                 # Start Cloudflare tunnel (idempotent)
browser-use tunnel list                   # Show active tunnels
browser-use tunnel stop <port>            # Stop tunnel
browser-use tunnel stop --all             # Stop all tunnels
```

## Profile Management

```bash
browser-use profile list                  # List detected browsers and profiles
browser-use profile sync --all            # Sync profiles to cloud
browser-use profile update                # Download/update profile-use binary
```

## Command Chaining

Commands can be chained with `&&`. The browser persists via the daemon, so chaining is safe and efficient.

```bash
browser-use open https://example.com && browser-use state
browser-use input 5 "user@example.com" && browser-use input 6 "password" && browser-use click 7
```

Chain when you don't need intermediate output. Run separately when you need to parse `state` to discover indices first.

## Common Workflows

### Authenticated Browsing

When a task requires an authenticated site (Gmail, GitHub, internal tools), use Chrome profiles:

```bash
browser-use profile list                           # Check available profiles
# Ask the user which profile to use, then:
browser-use --profile "Default" open https://github.com  # Already logged in
```

### Connecting to Existing Chrome

```bash
browser-use --connect open https://example.com     # Auto-discovers Chrome's CDP endpoint
```

Requires Chrome with remote debugging enabled. Falls back to probing ports 9222/9229.

### Exposing Local Dev Servers

```bash
browser-use tunnel 3000                            # → https://abc.trycloudflare.com
browser-use open https://abc.trycloudflare.com     # Browse the tunnel
```

## Global Options

| Option | Description |
|--------|-------------|
| `--headed` | Show browser window |
| `--profile [NAME]` | Use real Chrome (bare `--profile` uses "Default") |
| `--connect` | Auto-discover running Chrome via CDP |
| `--cdp-url <url>` | Connect via CDP URL (`http://` or `ws://`) |
| `--session NAME` | Target a named session (default: "default") |
| `--json` | Output as JSON |
| `--mcp` | Run as MCP server via stdin/stdout |

## Tips

1. **Always run `state` first** to see available elements and their indices
2. **Use `--headed` for debugging** to see what the browser is doing
3. **Sessions persist** — browser stays open between commands
4. **CLI aliases**: `bu`, `browser`, and `browseruse` all work

## Troubleshooting

- **Browser won't start?** `browser-use close` then `browser-use --headed open <url>`
- **Element not found?** `browser-use scroll down` then `browser-use state`
- **Run diagnostics:** `browser-use doctor`

## Cleanup

```bash
browser-use close                         # Close browser session
browser-use tunnel stop --all             # Stop tunnels (if any)
```
