# Python

Use the same browser agent from Python.

Requires **Python 3.11+**, **Node.js 22.19+** and **Chrome**. Set your [model API key](/models#api-keys) in the environment.

## Install

From the [source checkout](/quickstart#_1-install):

```sh
npm run build:python
uv build python --wheel --out-dir artifacts/python
uv venv
uv pip install artifacts/python/browser_use_next-0.1.0-py3-none-any.whl
```

The wheel bundles the JavaScript engine. Once built, users only need the wheel, Node and Chrome. It is not on PyPI yet.

## Run an agent

Save as `agent.py`:

```python
import asyncio
from browser_use_next import BrowserUse

async def main():
    async with await BrowserUse.create(
        model='openai/gpt-5.5',
        workspace='./work/research',
    ) as agent:
        result = await agent.run('Find the top story on Hacker News.')
        print(result.status, result.text)
        await agent.follow_up('Summarize the comments.')

asyncio.run(main())
```

```sh
uv run agent.py
```

Use `browser={'profileDir': './profiles/work'}` to keep a login. Use `schema=YourPydanticModel` for typed output.

## Add a Python tool

```python
import asyncio
from pydantic import BaseModel
from browser_use_next import BrowserUse, Tool

class Quantity(BaseModel):
    quantity: int

class Quote(BaseModel):
    total: int

async def quote(args: Quantity) -> Quote:
    return Quote(total=args.quantity * 7)

async def main():
    async with await BrowserUse.create(
        model='openai/gpt-5.5',
        tools=[Tool('quote', 'Price the requested quantity', Quantity, quote)],
    ) as agent:
        result = await agent.run('Price three units.', schema=Quote)
        if result.status == 'completed':
            print(result.output.total)

asyncio.run(main())
```

Your callback stays in Python. The agent loop runs in the bundled JS engine.

::: details Tool schemas & cancellation
Parameters and results are validated with Pydantic. Non-recursive local schema references are inlined before sending nested tool schemas; recursive/external references fail explicitly. A tool exception becomes an error result for the agent. Async tool tasks are cancelled when the Node call is cancelled; synchronous tools run in a thread and must cooperate with application cancellation because Python cannot kill their thread safely. Tool RPC has a 120-second ceiling.
:::

::: details Streaming, configuration & hooks
`events()` is an async iterator. Start consuming before `run()` to see its first event. It has a bounded 64-event queue; a slow consumer receives an explicit error. Methods include `pause()`, `resume()`, `steer(text)`, `cancel()`, `execute(code)`, `files()`, `history()`, `save_history()` and `export_recording()`.

`run()` and `follow_up()` accept `schema` as a Pydantic model or JSON Schema dictionary. Other configuration/run options use the JavaScript SDK's names, such as `timeoutMs` and `maxSteps`. Unsupported bridge options fail explicitly. For custom endpoints, `baseUrl` and `apiKey` are sent through stdin, not command-line arguments. Use an explicit model ID supported by the configured Pi provider; arbitrary Python LLM objects are not silently reduced to model strings.

The Python wrapper exposes the session API and Python custom tools. JavaScript callback hooks are available in the JS SDK; this release does not serialize Python hook functions. Use Python custom tools for business checks and the event/control API for intervention.
:::

::: details Migration & runtime support
Use `from browser_use_next import BrowserUse`. This is a separate client; it does not change `browser_use.beta.Agent` or accept its full constructor.

Pass `node='/path/to/node'` to select Node explicitly. The wheel was tested on macOS with Python 3.14. Python 3.11, Linux and Windows have not been exercised. [Verification](/session-verification).

:::
