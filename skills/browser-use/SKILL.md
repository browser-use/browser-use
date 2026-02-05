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
browser-use --browser chromium open <url>           # Default: headless Chromium
browser-use --browser chromium --headed open <url>  # Visible Chromium window
browser-use --browser real --profile "Default" open <url>
browser-use --browser real --browser-exe <path> --user-data-dir <path> open <url>
browser-use --browser remote open <url>             # Cloud browser (requires API key)
```

- **chromium**: Fast, isolated, headless by default
- **real**: Uses your Chrome profile (copies profile by default)
- **remote**: Cloud-hosted browser with proxy support (requires BROWSER_USE_API_KEY)

Real browser notes:
- Use `--no-copy-profile` or `BROWSER_USE_NO_COPY_PROFILE=1` to use the profile in-place
- Use `--browser-exe`, `--user-data-dir`, and `--profile` to target a specific Chrome profile

## Commands

### Navigation
```bash
browser-use open <url>                    # Navigate to URL
browser-use back                          # Go back in history
browser-use scroll down                   # Scroll down
browser-use scroll up                     # Scroll up
browser-use scroll down --amount 800      # Scroll with custom pixel amount
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
browser-use python -f script.py           # Short alias for --file
```

The Python session maintains state across commands. The `browser` object provides:
- `browser.url` - Current page URL
- `browser.title` - Page title
- `browser.goto(url)` - Navigate
- `browser.click(index)` - Click element
- `browser.type(text)` - Type text
- `browser.screenshot(path)` - Take screenshot
- `browser.scroll()` - Scroll page
- `browser.html` - Get page HTML

### Agent Tasks (Requires API Key)
```bash
browser-use run "Fill the contact form with test data"    # Run AI agent
browser-use run "Extract all product prices" --max-steps 50
```

Agent tasks use an LLM to autonomously complete complex browser tasks. Requires `BROWSER_USE_API_KEY` or configured LLM API key (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc).

### Session Management
```bash
browser-use sessions                      # List active sessions
browser-use close                         # Close current session
browser-use close --all                   # Close all sessions
```

### Profile Management
```bash
browser-use profile list-local            # List local Chrome profiles
```

**Before opening a real browser (`--browser real`)**, always ask the user if they want to use a specific Chrome profile or no profile. Use `profile list-local` to show available profiles:

```bash
browser-use profile list-local
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

### Cloud Profiles

Cloud profiles store browser state (cookies) in Browser-Use Cloud, persisting across sessions. Requires `BROWSER_USE_API_KEY`.

```bash
browser-use profile list                      # List cloud profiles
browser-use profile get <id>                  # Get profile details
browser-use profile update <id> --name "New"  # Rename profile
browser-use profile delete <id>               # Delete profile
```

Use a cloud profile with `--browser remote --profile <id>`:

```bash
browser-use --browser remote --profile abc-123 open https://example.com
```

### Syncing Cookies to Cloud

**⚠️ IMPORTANT: Before syncing cookies from a local browser to the cloud, the agent MUST:**
1. Ask the user which local Chrome profile to use (`browser-use profile list-local`)
2. Ask which domain(s) to sync - do NOT default to syncing the full profile
3. Confirm before proceeding

**Default behavior:** Create a NEW cloud profile for each domain sync. This ensures clear separation of concerns for cookies. Users can add cookies to existing profiles if needed.

**Step 1: List available profiles and cookies**

```bash
# List local Chrome profiles
browser-use profile list-local
# → Default: Person 1 (user@gmail.com)
# → Profile 1: Work (work@company.com)

# See what cookies are in a profile
browser-use profile cookies "Default"
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
| `--session NAME`, `-s` | Use named session (default: "default") |
| `--browser MODE`, `-b` | Browser mode: chromium, real, remote |
| `--headed` | Show browser window (chromium mode) |
| `--browser-exe PATH` | Path to Chrome/Chromium executable (real mode) |
| `--user-data-dir PATH` | Chrome user data directory (real mode) |
| `--profile NAME` | Cloud profile id (remote mode) or Chrome profile directory name (real mode) |
| `--no-copy-profile` | Use profile in-place without copying |
| `--json` | Output as JSON |
| `--api-key KEY` | Override API key |

Note: In real mode, `--profile` expects a directory name under `--user-data-dir` (for example `Default` or `Profile 1`), which is what Chromium expects. In remote mode, it is the cloud profile id.

**Session behavior**: All commands without `--session` use the same "default" session. The browser stays open and is reused across commands. Use `--session NAME` to run multiple browsers in parallel.

## API Key Configuration

Some features (`run`, `extract`, `--browser remote`) require an API key. The CLI checks these locations in order:

1. `--api-key` command line flag
2. `BROWSER_USE_API_KEY` environment variable
3. `~/.config/browseruse/config.json` file

To configure permanently:
```bash
mkdir -p ~/.config/browseruse
echo '{"api_key": "your-key-here"}' > ~/.config/browseruse/config.json
```

Set `BROWSER_USE_CONFIG_DIR` to override the config location.

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
browser-use --browser real --profile "Default" open https://gmail.com
# Use profile in-place (skip temporary copy)
browser-use --browser real --no-copy-profile open https://gmail.com
# Uses your actual Chrome with existing login sessions
browser-use state  # Already logged in!
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
