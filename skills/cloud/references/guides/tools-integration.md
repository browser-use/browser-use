# Guide: Adding Browser-Use Tools to Your Agent

Add individual browser actions to your existing agent's tool set. Your agent stays in control and drives the browser action by action.

## Table of Contents
- [When to Use This Pattern](#when-to-use-this-pattern)
- [Pick Your Integration](#pick-your-integration)
- [Shell Command Agents (CLI)](#shell-command-agents-cli)
- [TypeScript/JS: CDP + Playwright](#typescriptjs-cdp--playwright)
- [MCP-Native Agents](#mcp-native-agents)
- [Existing Playwright/Puppeteer/Selenium](#existing-playwrightpuppeteerselenium)
- [Decision Summary](#decision-summary)

---

## When to Use This Pattern

Your agent already has tools (search, code execution, file I/O, etc.) and its own reasoning loop. You want to add browser capabilities — navigate, click, type, extract — as tools your agent can call. You don't want to hand off to browser-use's Agent; your agent makes the decisions.

**Use tools integration when:**
- Your agent needs action-by-action browser control
- You want browser actions alongside your other tools
- Your agent's reasoning should drive what gets clicked/typed

**Use [subagent](subagent.md) instead when:**
- You want to delegate an entire web task as a black box
- You don't need control over individual browser actions

## Pick Your Integration

| Your agent type | Best approach | Control level |
|----------------|---------------|--------------|
| CLI coding agent in sandbox | [CLI 3.0 Python](#shell-command-agents-cli) | Per-call |
| TypeScript/JS | [CDP + Playwright](#typescriptjs-cdp--playwright) | Playwright API |
| MCP client (Claude Desktop, Cursor) | [Local MCP server](#mcp-native-agents) | MCP tools |
| Existing Playwright/Puppeteer/Selenium | [CDP WebSocket (stealth)](#existing-playwrightpuppeteerselenium) | Your existing API |
| HTTP only / any language | Cloud REST: `POST /browsers` → CDP URL | CDP |

---

## Shell Command Agents (CLI)

**For:** Claude Code, Codex, OpenCode, Cline, Windsurf, Cursor background agents, Hermes, OpenClaw — any coding agent running in a VM/container with terminal access.

**Setup:** Install the CLI and load the browser-use SKILL.md into the agent's context. CLI 3.0 runs Python from stdin. Browser helpers are already imported, and the browser stays alive between calls.

```bash
uv pip install 'browser-use[cli]'
```

For Browser Use Cloud, authenticate once and start a named remote browser:

```bash
browser-use auth login

browser-use <<'PY'
start_remote_daemon("agent-1")
PY
```

Use the same `BU_NAME` for every later call so the agent stays on that cloud browser:

```bash
# 1. Navigate and observe
BU_NAME=agent-1 browser-use <<'PY'
new_tab("https://html.duckduckgo.com/html/")
wait_for_load()
print(page_info())
PY

# 2. Interact, then verify the result
BU_NAME=agent-1 browser-use <<'PY'
fill_input('input[name="q"]', "search query")
press_key("ENTER")
wait_for_load()
print(js("document.title"))
print(capture_screenshot())
PY

# 3. Stop the cloud browser when the job is done
browser-use <<'PY'
stop_remote_daemon("agent-1")
PY
```

**Key details:**
- CLI 3.0 removed the old `open`, `state`, `click`, `eval`, `--json`, `--headed`, and `--profile` command surface.
- The agent writes Python with helpers such as `new_tab`, `page_info`, `fill_input`, `click_at_xy`, `js`, and `cdp`.
- The background daemon keeps the browser alive between calls. Printed Python values are the tool output.
- `BU_NAME` selects the named cloud browser. Without it, the CLI uses the default local browser.
- The first navigation is `new_tab(url)`. Use `goto_url(url)` only after a real tab exists.
- Remote browsers keep billing until they stop or time out. Always call `stop_remote_daemon(name)` after the job.

---

## TypeScript/JS: CDP + Playwright

**For:** TypeScript agents that need browser primitives. Connect Playwright to a cloud stealth browser.

```typescript
import { chromium } from "playwright";

// Connect to cloud stealth browser (no local Chrome needed)
const browser = await chromium.connectOverCDP(
  "wss://connect.browser-use.com?apiKey=YOUR_KEY&proxyCountryCode=us"
);
const page = browser.contexts()[0].pages()[0];

// Your agent calls these as tools:
await page.goto("https://example.com");
await page.fill("#search", "query");
await page.click("button[type=submit]");
const text = await page.textContent(".result");
const screenshot = await page.screenshot();

await browser.close();
// Browser auto-stops when WebSocket disconnects
```

For local browser (no cloud):
```typescript
import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage();
// ... same Playwright API
await browser.close();
```

---

## MCP-Native Agents

**For:** Claude Desktop, Cursor with MCP, any MCP client that discovers tools via protocol.

Start the local MCP server:
```bash
uvx --from 'browser-use[cli]' browser-use --mcp
```

The agent gets individual browser tools:
- `browser_navigate(url)` — go to URL
- `browser_click(index)` — click element by index
- `browser_type(index, text)` — type into element
- `browser_get_state(include_screenshot)` — get page state with element indices
- `browser_extract_content(query)` — LLM-powered extraction
- `browser_screenshot(full_page)` — capture page
- `browser_scroll(direction)` — scroll up/down
- `browser_go_back()` — browser back
- `browser_list_tabs()`, `browser_switch_tab(id)`, `browser_close_tab(id)` — tab management

The agent calls these one at a time, using its own reasoning to decide the next action.

---

## Existing Playwright/Puppeteer/Selenium

**For:** You already have browser automation scripts and want to run them on stealth infrastructure (anti-fingerprinting, CAPTCHA handling, residential proxies).

Zero code changes — just change the connection URL:

### Playwright
```python
# Before: local browser
browser = await playwright.chromium.launch()

# After: cloud stealth browser
browser = await playwright.chromium.connect_over_cdp(
    "wss://connect.browser-use.com?apiKey=KEY&proxyCountryCode=us"
)
# Rest of your code stays exactly the same
```

### Puppeteer
```javascript
// Before
const browser = await puppeteer.launch();

// After
const browser = await puppeteer.connect({
  browserWSEndpoint: "wss://connect.browser-use.com?apiKey=KEY&proxyCountryCode=us"
});
```

Browser auto-starts on connect, auto-stops on disconnect. Pricing: $0.05/hour.

---

## Decision Summary

| Condition | Best option |
|-----------|------------|
| Agent has terminal access (sandbox/VM) | CLI commands |
| TypeScript/JS | CDP WebSocket + Playwright |
| MCP client (Claude Desktop, Cursor) | Local MCP server |
| HTTP only / any language | Cloud REST: `POST /browsers` → CDP URL |
| Existing Playwright/Puppeteer scripts | CDP WebSocket (stealth cloud browser) |

> **Note:** For Python agents that want fine-grained browser control via direct imports (Actor API, Tools Registry, MCPClient), see the **open-source** skill's reference docs.
