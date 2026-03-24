# Example Patterns & Templates

## Table of Contents
- [Fast Agent](#fast-agent)
- [Parallel Browsers](#parallel-browsers)
- [Follow-Up Tasks](#follow-up-tasks)
- [Sensitive Data](#sensitive-data)
- [Playwright Integration](#playwright-integration)

---

## Fast Agent

Maximize speed with optimized config:

```python
from browser_use import Agent, Browser, BrowserProfile, ChatGroq

# Fast LLM (Groq or Gemini Flash Lite)
llm = ChatGroq(model="meta-llama/llama-4-maverick-17b-128e-instruct")

# Minimize wait times
browser = Browser(
    minimum_wait_page_load_time=0.1,
    wait_between_actions=0.1,
)

agent = Agent(
    task="Find top HN post",
    llm=llm,
    browser=browser,
    flash_mode=True,  # Skip LLM thinking, use memory only
    extend_system_message="Be fast. Execute multiple actions per step.",
)

await agent.run()
```

**Key optimizations:**
- `flash_mode=True` — skip evaluation, next goal, thinking
- Low wait times — `0.1` instead of defaults
- Fast LLM — Groq or Gemini Flash Lite
- Multi-action prompts — fill multiple fields per step

## Parallel Browsers

Run multiple agents concurrently:

```python
import asyncio
from browser_use import Agent, Browser, ChatBrowserUse

async def run_task(task: str, index: int):
    browser = Browser(user_data_dir=f'./temp-profile-{index}')
    try:
        agent = Agent(task=task, llm=ChatBrowserUse(), browser=browser)
        result = await agent.run()
        return result
    finally:
        await browser.close()

async def main():
    tasks = [
        "Find the latest AI news on TechCrunch",
        "Get Bitcoin price from CoinGecko",
        "Find top Python packages on PyPI",
    ]
    results = await asyncio.gather(*[run_task(t, i) for i, t in enumerate(tasks)])
```

Each agent gets its own browser with a separate profile to avoid conflicts.

## Follow-Up Tasks

Chain tasks in a persistent browser session:

```python
from browser_use import Agent, Browser, ChatBrowserUse

browser = Browser(keep_alive=True)
await browser.start()

agent = Agent(
    task="Go to GitHub and search for 'browser-use'",
    llm=ChatBrowserUse(),
    browser=browser,
)
await agent.run()

# Queue follow-up in same browser (cookies/localStorage preserved)
agent.add_new_task("Click on the first repository and extract the star count")
await agent.run()

await browser.close()
```

`keep_alive=True` keeps browser open between tasks. Agent maintains memory and browser state.

## Sensitive Data

Handle credentials without exposing to LLM:

```python
agent = Agent(
    task="Login to example.com",
    llm=llm,
    sensitive_data={
        'x_user': 'my-username',       # All sites
        'x_pass': 'my-password',       # All sites
    },
    browser=Browser(allowed_domains=['*.example.com']),
)
```

- LLM sees placeholder names (`x_user`, `x_pass`), not real values
- Real values injected into form fields at execution time
- Never appears in logs or LLM context

### Per-Domain Credentials

```python
sensitive_data = {
    'github_user': 'gh-username',
    'github_pass': 'gh-password',
    'gmail_user': 'gmail-address',
}
```

### Best Practices

- Use `Browser(allowed_domains=[...])` to restrict navigation
- Set `use_vision=False` for sensitive pages
- Prefer `storage_state='auth.json'` over sending passwords
- Use TOTP secrets with `bu_2fa_code` suffix for 2FA (see `browser.md`)

## Playwright Integration

Share Chrome between Playwright and Browser-Use via CDP:

```python
import subprocess
from playwright.async_api import async_playwright
from browser_use import Agent, Browser, Tools, ChatBrowserUse

# 1. Start Chrome with remote debugging
proc = subprocess.Popen([
    'google-chrome', '--remote-debugging-port=9222', '--user-data-dir=/tmp/chrome-debug'
])

pw = None
try:
    # 2. Connect Playwright
    pw = await async_playwright().start()
    pw_browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
    pw_page = pw_browser.contexts[0].pages[0]

    # 3. Connect Browser-Use to same Chrome
    browser = Browser(cdp_url="http://localhost:9222")

    # 4. Custom tools using Playwright
    tools = Tools()

    @tools.action(description='Fill form field using Playwright selector')
    async def pw_fill(selector: str, value: str) -> str:
        await pw_page.fill(selector, value)
        return f'Filled {selector}'

    @tools.action(description='Take Playwright screenshot')
    async def pw_screenshot() -> str:
        await pw_page.screenshot(path='screenshot.png')
        return 'Screenshot saved'

    # 5. Agent orchestrates using both
    agent = Agent(task="Fill out the form", llm=ChatBrowserUse(), browser=browser, tools=tools)
    await agent.run()
finally:
    if pw:
        await pw.stop()
    proc.terminate()
    proc.wait()
```

Both Playwright and Browser-Use operate on the same pages through the shared CDP connection.
