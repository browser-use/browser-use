# Quickstart & Production Deployment

## Table of Contents
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [First Agent](#first-agent)
- [Production with @sandbox](#production-with-sandbox)

---

## Installation

```bash
pip install uv
uv venv --python 3.12
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install browser-use
uvx browser-use install     # Downloads Chromium
```

## Environment Variables

```bash
# Browser Use (recommended) — https://cloud.browser-use.com/new-api-key
BROWSER_USE_API_KEY=

# Google — https://aistudio.google.com/app/u/1/apikey
GOOGLE_API_KEY=

# OpenAI
OPENAI_API_KEY=

# Anthropic
ANTHROPIC_API_KEY=
```

## First Agent

### ChatBrowserUse (Recommended — fastest, cheapest, highest accuracy)

```python
from browser_use import Agent, ChatBrowserUse
from dotenv import load_dotenv
import asyncio

load_dotenv()

async def main():
    llm = ChatBrowserUse()
    agent = Agent(task="Find the number 1 post on Show HN", llm=llm)
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
```

### Google Gemini

```python
from browser_use import Agent, ChatGoogle
from dotenv import load_dotenv
import asyncio

load_dotenv()

async def main():
    llm = ChatGoogle(model="gemini-flash-latest")
    agent = Agent(task="Find the number 1 post on Show HN", llm=llm)
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
```

### OpenAI

```python
from browser_use import Agent, ChatOpenAI
from dotenv import load_dotenv
import asyncio

load_dotenv()

async def main():
    llm = ChatOpenAI(model="gpt-4.1-mini")
    agent = Agent(task="Find the number 1 post on Show HN", llm=llm)
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
```

### Anthropic

```python
from browser_use import Agent, ChatAnthropic
from dotenv import load_dotenv
import asyncio

load_dotenv()

async def main():
    llm = ChatAnthropic(model='claude-sonnet-4-0', temperature=0.0)
    agent = Agent(task="Find the number 1 post on Show HN", llm=llm)
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
```

See `references/open-source/models.md` for all 15+ providers.

---

## Production with @sandbox

The `@sandbox` decorator is the easiest way to deploy to production. The agent runs next to the browser on cloud infrastructure with minimal latency.

### Basic Deployment

```python
from browser_use import Browser, sandbox, ChatBrowserUse
from browser_use.agent.service import Agent
import asyncio

@sandbox()
async def my_task(browser: Browser):
    agent = Agent(task="Find the top HN post", browser=browser, llm=ChatBrowserUse())
    await agent.run()

asyncio.run(my_task())
```

### With Proxies

```python
@sandbox(cloud_proxy_country_code='us')
async def stealth_task(browser: Browser):
    agent = Agent(task="Your task", browser=browser, llm=ChatBrowserUse())
    await agent.run()
```

### With Authentication (Profile Sync)

1. Sync local cookies:
```bash
export BROWSER_USE_API_KEY=your_key && curl -fsSL https://browser-use.com/profile.sh | sh
```

2. Use the returned profile_id:
```python
@sandbox(cloud_profile_id='your-profile-id')
async def authenticated_task(browser: Browser):
    agent = Agent(task="Your authenticated task", browser=browser, llm=ChatBrowserUse())
    await agent.run()
```

### Sandbox Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `BROWSER_USE_API_KEY` | str | API key (env var) | Required |
| `cloud_profile_id` | str | Browser profile UUID | None |
| `cloud_proxy_country_code` | str | us, uk, fr, it, jp, au, de, fi, ca, in | None |
| `cloud_timeout` | int | Minutes (max: 15 free, 240 paid) | None |
| `on_browser_created` | Callable | Receives `data.live_url` | None |
| `on_log` | Callable | Receives `log.level`, `log.message` | None |
| `on_result` | Callable | Success callback | None |
| `on_error` | Callable | Receives `error.error` | None |

### Event Callbacks

```python
from browser_use.sandbox import BrowserCreatedData, LogData, ResultData, ErrorData

@sandbox(
    cloud_profile_id='your-profile-id',
    cloud_proxy_country_code='us',
    on_browser_created=lambda data: print(f'Live: {data.live_url}'),
    on_log=lambda log: print(f'{log.level}: {log.message}'),
    on_result=lambda result: print('Done!'),
    on_error=lambda error: print(f'Error: {error.error}'),
)
async def task(browser: Browser):
    agent = Agent(task="your task", browser=browser, llm=ChatBrowserUse())
    await agent.run()
```

All callbacks can be sync or async.

### Local Development

```bash
git clone https://github.com/browser-use/browser-use
cd browser-use
uv sync --all-extras --dev

# Helper scripts
./bin/setup.sh   # Complete setup
./bin/lint.sh    # Formatting, linting, type checking
./bin/test.sh    # CI test suite

# Run examples
uv run examples/simple.py
```

### Telemetry

Opt out with `ANONYMIZED_TELEMETRY=false` env var. Zero performance impact.
