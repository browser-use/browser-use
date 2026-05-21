# Browser-Use — Quick Start

> **AI BROWSER AGENT** · Tell it what to do. Watch it go.

---

## What it is

Browser-Use gives an LLM eyes and hands in a real browser.
You write a task in plain English. It navigates, clicks, types, reads, and reports back.

```
3 commands to install    ·    ~50 ms per browser action    ·    15+ LLM providers
```

**No GUI required. No account needed. Free and open source (MIT).**

---

## 60-Second Install

```bash
# 1. Install (Python 3.11+ required)
pip install browser-use

# 2. Verify
PYTHONIOENCODING=utf-8 browser-use doctor

# 3. Done — run your first task (see below)
```

> **Windows?** Run via `uv` from the project root if `browser-use` isn't in PATH yet:
> `uv run browser-use doctor`

---

## Your First Task — Copy & Run

```python
# task.py
import asyncio
from browser_use import Agent, Browser
from browser_use.llm import ChatAnthropic  # or ChatOpenAI, ChatGoogle, ChatOllama…

async def main():
    agent = Agent(
        task="Go to news.ycombinator.com and give me the top 3 headlines",
        llm=ChatAnthropic(model="claude-sonnet-4-6"),
        browser=Browser(),
    )
    result = await agent.run()
    print(result)

asyncio.run(main())
```

Set your key, run it, and you'll see a real browser open, navigate, and return structured results — in under 30 seconds.

```bash
export ANTHROPIC_API_KEY=your-key   # or OPENAI_API_KEY, GOOGLE_API_KEY, etc.
python task.py
```

---

## Choose Your Path

Three ways to use browser-use — pick one to start, combine later:

### ① CLI — Fastest to a result, no Python needed

```bash
browser-use open https://example.com   # open a page
browser-use state                       # see all clickable elements
browser-use click 5                     # click by index
browser-use screenshot page.png         # capture
browser-use close                       # done
```

Best for: interactive exploration, one-off tasks, scripting in bash.

---

### ② Python Agent — Full power, any task

```python
from browser_use import Agent, Browser, Tools

agent = Agent(
    task="Find the cheapest flight from Paris to Lisbon next Friday",
    llm=your_llm,
    browser=Browser(),
)
await agent.run()
```

Best for: multi-step automation, data extraction, form-filling pipelines.

**Add custom tools** to extend what the agent can do:

```python
tools = Tools()

@tools.action(description="Save a job listing to my database")
def save_job(title: str, company: str, url: str) -> str:
    # your logic here
    return f"Saved: {title} at {company}"

agent = Agent(task="...", llm=llm, browser=Browser(), tools=tools)
```

---

### ③ Cloud Browser — Production-ready, zero local setup

```bash
browser-use cloud login YOUR_API_KEY   # one-time setup
browser-use cloud connect              # stealth browser provisions in seconds
browser-use open https://example.com   # all commands work the same
```

Best for: sites with CAPTCHAs, anti-bot detection, or when you need
proxy rotation, persistent profiles, and parallel scale.

Get an API key → [cloud.browser-use.com](https://cloud.browser-use.com)

---

## Top 3 First Real Tasks

Copy any of these straight into a `task.py`:

**1 — Screenshot a page**
```python
task = "Go to github.com/browser-use/browser-use and take a screenshot"
```

**2 — Extract structured data**
```python
task = "Search 'python developer remote' on LinkedIn Jobs and list the first 5 results: title, company, location"
```

**3 — Fill a form**
```python
task = "Go to httpbin.org/forms/post, fill in the form with test data, and tell me what the response says"
```

---

## LLM Provider Quick-Reference

| Provider | Import | Key env var |
|---|---|---|
| Browser-Use (recommended) | `ChatBrowserUse()` | `BROWSER_USE_API_KEY` |
| Anthropic | `ChatAnthropic(model="claude-sonnet-4-6")` | `ANTHROPIC_API_KEY` |
| OpenAI | `ChatOpenAI(model="gpt-4o")` | `OPENAI_API_KEY` |
| Google | `ChatGoogle(model="gemini-2.5-flash")` | `GOOGLE_API_KEY` |
| Local (Ollama) | `ChatOllama(model="llama3.2")` | *(none)* |

`ChatBrowserUse()` is the fastest and most accurate option for browser tasks — optimised specifically for this use case.

---

## Friction FAQ

**Do I need an account?**
No. Basic use (CLI + Python agent + local Chromium) is fully local and free. An account is only needed for the cloud browser.

**Which LLM should I use?**
Start with whatever API key you already have. `ChatBrowserUse()` is the best choice if you want the highest task completion rate.

**Does it work on Windows?**
Yes, with one caveat: the CLI outputs Unicode symbols (✓ ○) that crash in the default Windows terminal encoding. Prefix commands with `PYTHONIOENCODING=utf-8` or add it to your shell profile.

**Will it break things / submit forms without asking?**
By default, when using Claude Code with the browser-use skill active, all form submissions and account actions require explicit confirmation before executing. The agent never acts destructively without a checkpoint.

**How do I stop it mid-run?**
`Ctrl+C` stops the agent. Run `browser-use close` to cleanly shut down any open browser session.

---

## What's Next

| You want to… | Go to |
|---|---|
| Understand the 5-phase interaction protocol | [BLUEPRINT.md §2](BLUEPRINT.md#2-ux-design-the-interactive-agent-browsing-model) |
| See full command reference | [BLUEPRINT.md §3](BLUEPRINT.md#3-command-reference-quick-sheet) |
| Add your own tools / actions | [BLUEPRINT.md §5](BLUEPRINT.md#5-extending-the-agent) |
| Browse real-world examples | [`examples/`](examples/) |
| Read the full library docs | [docs.browser-use.com](https://docs.browser-use.com) |
| Open issues / contribute | [github.com/browser-use/browser-use](https://github.com/browser-use/browser-use) |

---

*Built with browser-use · MIT License · [browser-use.com](https://browser-use.com)*
