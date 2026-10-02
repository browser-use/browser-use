# Integrations

## Table of Contents
- [Anthropic browser toolset](#anthropic-browser-toolset)
- [MCP Server (Cloud)](#mcp-server-cloud)
- [MCP Server (Local)](#mcp-server-local)
- [Skills](#skills)
- [Documentation MCP](#documentation-mcp)

---

## Anthropic browser toolset

Browser Use and Anthropic collaborated so Claude can use Browser Use as the
driver behind Anthropic's browser toolset. Anthropic's SDK owns the model loop
and tool runner. Browser Use implements the 31 browser actions and connects
them to local Chromium, Browser Use Cloud, or an existing browser over CDP.

Requirements:

- Python 3.11 or newer
- An Anthropic SDK release with `anthropic.tools.browser` and
  `client.beta.messages.tool_runner`
- `ANTHROPIC_API_KEY` and the model ID Anthropic documents for the browser
  toolset
- `BROWSER_USE_API_KEY` only when using Browser Use Cloud. Create one at
  [cloud.browser-use.com/new-api-key](https://cloud.browser-use.com/new-api-key).

Install the packages and local Chromium:

```bash
uv init --python 3.12
uv add browser-use anthropic
uvx browser-use install
```

Create `run_browser.py`:

```python
import asyncio
import os
from pathlib import Path

from anthropic import AsyncAnthropic

from browser_use.integrations.anthropic import Bash, BrowserUse


async def main() -> None:
    task = 'Open example.com and save its page title to title.txt.'
    driver = BrowserUse()
    # driver = BrowserUse(use_cloud=True)  # Requires BROWSER_USE_API_KEY
    bash = Bash(output_dir=Path('outputs'))

    async with driver, AsyncAnthropic() as client:
        runner = client.beta.messages.tool_runner(
            model=os.environ['ANTHROPIC_MODEL'],
            max_tokens=32_768,
            max_iterations=1_000,
            tools=[driver, bash],
            messages=[{'role': 'user', 'content': task}],
        )
        final = await runner.until_done()

    print('\n'.join(block.text for block in final.content if block.type == 'text'))


asyncio.run(main())
```

Set the Anthropic variables and run it:

```bash
export ANTHROPIC_API_KEY=your-key
export ANTHROPIC_MODEL=your-model
# Optional SDK request and tool-runner logs
export ANTHROPIC_LOG=info

uv run run_browser.py
```

The `async with driver` block starts and closes a driver-owned local or Cloud
browser. When passing an already-started `BrowserSession`, the application
starts and closes that session instead.

`BrowserUse` implements all 31 actions. Anthropic leaves
`javascript_exec`, `file_upload`, `read_console`, and `read_network`
disabled by default. Enable only the capabilities the application needs:

```python
async def confirm(context):
    if context.member not in {'javascript_exec', 'file_upload'}:
        return True
    return await app.approve(context.member, context.tab_url)


driver = BrowserUse(
    confirm=confirm,
    configs={
        'javascript_exec': {'enabled': True},
        'file_upload': {'enabled': True},
        'read_console': {'enabled': True},
        'read_network': {'enabled': True},
    },
)
```

`Bash` is a separate bounded tool for local computation and deliverables:

```python
bash = Bash(output_dir='outputs', timeout_seconds=120, max_output_bytes=50_000)
```

Bash strips ambient credentials from child commands and limits execution time
and returned output. Its working directory is a file boundary, not an operating
system sandbox. Run the SDK process in your normal container or sandbox for
untrusted tasks.

For a remote browser, upload paths must already exist on the browser host.
Local files created by Bash are not copied to that host automatically. Use the
SDK's file policy and a `document_resolver` that maps approved document IDs to
browser-host paths.

See the complete
[quickstart, runtime examples, action list, and file guidance](../../../examples/integrations/anthropic/README.md).

---

## MCP Server (Cloud)

HTTP-based MCP server at `https://api.browser-use.com/mcp`

### Setup

**Claude Code:**
```bash
claude mcp add --transport http browser-use https://api.browser-use.com/mcp
```

**Claude Desktop** (macOS `~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "browser-use": {
      "type": "http",
      "url": "https://api.browser-use.com/mcp",
      "headers": { "x-browser-use-api-key": "your-api-key" }
    }
  }
}
```

**Cursor** (`~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "browser-use": {
      "type": "http",
      "url": "https://api.browser-use.com/mcp",
      "headers": { "x-browser-use-api-key": "your-api-key" }
    }
  }
}
```

**Windsurf** (`~/.codeium/windsurf/mcp_config.json`):
```json
{
  "mcpServers": {
    "browser-use": {
      "type": "http",
      "url": "https://api.browser-use.com/mcp",
      "headers": { "x-browser-use-api-key": "your-api-key" }
    }
  }
}
```

### Cloud MCP Tools

| Tool | Cost | Description |
|------|------|-------------|
| `browser_task` | $0.01 + per-step | Run browser automation task |
| `execute_skill` | $0.02 | Execute a skill |
| `list_skills` | Free | List available skills |
| `get_cookies` | Free | Get cookies |
| `list_browser_profiles` | Free | List cloud profiles |
| `monitor_task` | Free | Check task progress |

`browser_task` params: `task` (required), `max_steps` (1-10, default 8), `profile_id` (UUID)

---

## MCP Server (Local)

Free, self-hosted stdio-based server:

```bash
uvx --from 'browser-use[cli]' browser-use --mcp
```

### Claude Desktop Config

macOS (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "browser-use": {
      "command": "/Users/your-username/.local/bin/uvx",
      "args": ["--from", "browser-use[cli]", "browser-use", "--mcp"],
      "env": {
        "OPENAI_API_KEY": "your-key"
      }
    }
  }
}
```

Note: Use full path to `uvx` on macOS/Linux (run `which uvx` to find it).

### Local MCP Tools

**Agent:** `retry_with_browser_use_agent` — full automation task

**Direct Control:**
- `browser_navigate` — Go to URL
- `browser_click` — Click element by index
- `browser_type` — Type text
- `browser_get_state` — Page state + interactive elements
- `browser_scroll` — Scroll page
- `browser_go_back` — Back in history

**Tabs:** `browser_list_tabs`, `browser_switch_tab`, `browser_close_tab`

**Extraction:** `browser_extract_content` — Structured extraction

**Sessions:** `browser_list_sessions`, `browser_close_session`, `browser_close_all`

### Environment Variables

- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` — LLM key (required)
- `BROWSER_USE_HEADLESS` — `false` to show browser
- `BROWSER_USE_DISABLE_SECURITY` — `true` to disable security
- `BROWSER_USE_LOGGING_LEVEL` — `DEBUG` for verbose logs

### Programmatic Usage

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def use_browser_mcp():
    server_params = StdioServerParameters(
        command="uvx",
        args=["--from", "browser-use[cli]", "browser-use", "--mcp"]
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("browser_navigate", arguments={"url": "https://example.com"})
```

---

## Skills

Load cloud skills into agents as reusable API endpoints:

```python
agent = Agent(
    task='Analyze TikTok and Instagram profiles',
    skills=[
        'a582eb44-e4e2-4c55-acc2-2f5a875e35e9',  # TikTok Scraper
        'f8d91c2a-3b4e-4f7d-9a1e-6c8e2d3f4a5b',  # Instagram Scraper
    ],
    llm=ChatBrowserUse()
)
await agent.run()
```

- Use `skills=['*']` for all skills (each adds ~200 tokens to prompt)
- Requires `BROWSER_USE_API_KEY`
- Browse/create at [cloud.browser-use.com/skills](https://cloud.browser-use.com/skills)
- Cookies auto-injected from browser; if missing, LLM navigates to obtain them

---

## Documentation MCP

Read-only docs access (no browser automation):

**Claude Code:**
```bash
claude mcp add --transport http browser-use-docs https://docs.browser-use.com/mcp
```

**Cursor** (`~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "browser-use-docs": { "url": "https://docs.browser-use.com/mcp" }
  }
}
```

No API key needed. Provides API reference, config options, best practices, examples.
