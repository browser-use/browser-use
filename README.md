# Browser Use

Browser Use runs browser tasks through Pi with Python and TypeScript clients.
This branch prepares the next major version.
It creates no release.

## Install

```sh
uv add browser-use
```

Platform wheels contain a private Node runtime and the JavaScript engine.
Users need no separate Node installation.
Cloud browsers need `BROWSER_USE_API_KEY`.
A model needs its provider credentials.

## Run a task

```python
import asyncio
from browser_use import Agent

async def main():
    async with Agent(model="openai/gpt-6-luna") as agent:
        result = await agent.run("Find the top story on Hacker News.")
        print(result.status, result.text)

asyncio.run(main())
```

Omitting the browser selects Browser Use Cloud.
An explicit browser choice takes precedence.
The agent and its bash commands execute on the application machine.
The browser can execute remotely.

```sh
uvx browser-use run "Find the top story on Hacker News" --model openai/gpt-6-luna
uvx browser-use run "Read my dashboard" --model openai/gpt-6-luna --browser chrome
uvx browser-use run "Inspect example.com" --model openai/gpt-6-luna --browser chromium
```

The agent includes read, write, edit, and bash tools by default.
Set `researchTools=False` to hide those named tools.
That setting does not sandbox generated JavaScript.

## Use your existing Chrome

Enable remote debugging at `chrome://inspect/#remote-debugging`.
Accept Chrome's connection prompt when Chrome requires it.

```python
from browser_use import Agent, Browser

async with Agent(
    model="openai/gpt-6-luna",
    browser=Browser.chrome(),
) as agent:
    result = await agent.run("Read my dashboard.")
```

Chrome keeps its existing login and profile.
Closing the agent preserves the borrowed browser and unrelated tabs.
Discovery reads profiles on the application machine.
Use an explicit endpoint when Chrome runs on another machine.

```python
browser = Browser.cdp(cdp_url)
browser = Browser.chromium(profileDir="./profile", headless=False)
```

## Control execution

Use Python tools, structured results, approval callbacks, event streams, and trusted browser setup.
See [migration](docs/migration.md) and [enterprise controls](docs/enterprise.md).

Domain rules guard browser navigation.
Browser-side policy must enforce stronger browser restrictions.
The SDK does not restrict arbitrary host code through a CDP method list.

## Direct browser control

The `browser-use` command keeps the Browser Harness Python stdin interface.
Install its agent instructions with `browser-use skill install`.
The `run` command asks Pi to plan a task.
OpenAI and Anthropic adapters execute deterministic browser operations without another planning model.

## History and telemetry

Local history and recordings preserve task evidence.
Product telemetry records bounded usage, feature counters, timings, and classified errors.
It excludes raw task text, credentials, and full CDP URLs.

Disable product telemetry with `ANONYMIZED_TELEMETRY=false`, `DO_NOT_TRACK=1`, or `telemetry=False`.
The migration also preserves Browser Harness disable settings.

## Development

```sh
npm ci
npm run build:python
uv sync --dev --all-extras
./bin/test.sh
./bin/lint.sh
```

Source builds need Node 22.19 or later.
Platform wheels include Node for end users.

The source tree keeps Pi in `src/` and the Python client in `browser_use/`.
Historical implementations remain available through [legacy installation guidance](docs/legacy.md).
