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
Python and TypeScript `Agent` clients select `bu-auto` through the Browser Use gateway.
CLI tasks use the same default.
The gateway uses the same `BROWSER_USE_API_KEY`.
Explicit provider models use their own credentials.
Cloud browser usage and gateway model usage use your Browser Use account balance.

## Run from the command line

```sh
uvx browser-use auth login
uvx browser-use run "Find the top story on Hacker News"
```

The default needs no model selection or local browser installation.
You can manage credits in [Browser Use Cloud](https://cloud.browser-use.com/settings?tab=billing).

Select a model and inference service tier explicitly when needed:

```sh
uvx browser-use run "Research this company" --model bu-smart --service-tier ultrafast
```

The gateway controls service tier availability and pricing.
See [model configuration](docs/models.md) for model choices and fixed versions.

## Run from Python

Python reuses your saved CLI login.
For servers, create a key in [Browser Use Cloud](https://cloud.browser-use.com/settings?tab=api-keys&new=1).
Save the server key in a `.env` file:

```dotenv
BROWSER_USE_API_KEY=your-key
```

Save this script as `agent.py`:

```python
import asyncio
from browser_use import Agent

async def main():
    async with Agent(task="Find the top story on Hacker News.") as agent:
        result = await agent.run()
        print(result.final_result())

asyncio.run(main())
```

Run with your saved login:

```sh
uv run agent.py
```

For a server key, run `uv run --env-file .env agent.py`.

Use `follow_up(task)` to continue the same conversation.
See [Python examples](docs/python.md) for structured output and callbacks.

Omitting the browser selects Browser Use Cloud.
An explicit browser choice takes precedence.
The agent and its bash commands execute on the application machine.
The browser can execute remotely.

```sh
uvx browser-use run "Read my dashboard" --browser chrome
uvx browser-use run "Inspect example.com" --browser chromium
uvx browser-use run "Read my page" --cdp-url http://localhost:9222
```

The agent includes read, write, edit, and bash tools by default.
Set `research_tools=False` to hide those named tools.
That setting does not sandbox generated JavaScript.

## Run from TypeScript

```sh
npm install @browser_use/pi
```

```typescript
import { Agent } from '@browser_use/pi';

const agent = await Agent.create();
try {
  const result = await agent.run('Find the top story on Hacker News.');
  console.log(result.output);
} finally {
  await agent.close();
}
```

Set `BROWSER_USE_API_KEY` or pass `apiKey` to authenticate the gateway and default Cloud browser.
Node 22.19 or later runs the TypeScript client.

## Use your existing Chrome

Enable remote debugging at `chrome://inspect/#remote-debugging`.
Accept Chrome's connection prompt when Chrome requires it.

```python
from browser_use import Agent, Browser

async with Agent(
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
Product telemetry sends one final event with usage, feature counters, timings, and configuration.
It includes bounded task text, final responses, errors, warnings, and CDP URLs after credential removal.
Configured-secret redaction applies before upload.

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
Review [migration changes](docs/migration.md) before upgrading an existing application.
Keep `browser-use<1` when an application requires the old planner or BU2.
