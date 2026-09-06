# Python, same engine

The Python package runs the same Pi + raw-CDP engine through a versioned stdio bridge. It bundles the JavaScript runtime; no npm install is needed by a wheel consumer. Node.js 22.19+ and Chrome are still required. ffmpeg is needed only for video export.

## Build and install locally

Neither package is published yet. From the source checkout:

```sh
npm ci
npm run build:python
uv build python --wheel --out-dir artifacts/python
uv pip install artifacts/python/browser_use_next-0.1.0-py3-none-any.whl
```

The wheel includes the bundled server and worker. JavaScript dependencies are pinned by the npm lockfile and bundled at build time. Node is not downloaded or installed automatically. Pass `node='/path/to/node'` to select a runtime.

```python
from browser_use_next import BrowserUse

async with await BrowserUse.create(
    model='openai/gpt-5.5',
    workspace='./work/research',
    browser={'profileDir': './profiles/research'},
) as agent:
    result = await agent.run('Find three products matching the brief.')
    result = await agent.follow_up('Save those products as CSV.')
    print(result.status, result.output)
    print(await agent.files())
```

## Your functions remain Python

```python
from pydantic import BaseModel
from browser_use_next import BrowserUse, Tool

class Quantity(BaseModel):
    quantity: int

class Quote(BaseModel):
    total: int

async def quote(args: Quantity) -> Quote:
    return Quote(total=args.quantity * 7)

async with await BrowserUse.create(
    model='openai/gpt-5.5',
    tools=[Tool('quote', 'Price the requested quantity', Quantity, quote)],
) as agent:
    result = await agent.run('Price three units.', schema=Quote)
    if result.status == 'completed':
        print(result.output.total)
```

Parameters and results are validated with Pydantic. Non-recursive local schema references are inlined before sending nested tool schemas; recursive/external references fail explicitly. A tool exception becomes an error result for the agent. Async tool tasks are cancelled when the Node call is cancelled; synchronous tools run in a thread and must cooperate with application cancellation because Python cannot kill their thread safely. Tool RPC has a 120-second ceiling.

## Streaming and control

`events()` is an async iterator. Start consuming before `run()` to see its first event. It has a bounded 64-event queue; a slow consumer receives an explicit error. Methods include `pause()`, `resume()`, `steer(text)`, `cancel()`, `execute(code)`, `files()`, `history()`, `save_history()` and `export_recording()`.

`run()` and `follow_up()` accept `schema` as a Pydantic model or JSON Schema dictionary. Other configuration/run options use the JavaScript SDK's names, such as `timeoutMs` and `maxSteps`. Unsupported bridge options fail explicitly. For custom endpoints, `baseUrl` and `apiKey` are sent through stdin, not command-line arguments. Use an explicit model ID supported by the configured Pi provider; arbitrary Python LLM objects are not silently reduced to model strings.

The Python wrapper exposes the session API and Python custom tools. JavaScript callback hooks are available in the JS SDK; this release does not serialize Python hook functions. Use Python custom tools for business checks and the event/control API for intervention.

## Existing Browser Use beta

This package is an opt-in replacement engine, not a silent change to `browser_use.beta.Agent`. The existing Python Browser Use checkout and its users are untouched. Migration uses `from browser_use_next import BrowserUse` and an explicit model ID. The old 62-parameter compatibility surface is intentionally not emulated. There is one agent loop and a documented contract.
