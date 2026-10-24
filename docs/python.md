# Python client

The Python client uses the packaged Pi engine.
Platform wheels include a private Node runtime.
The package requires Python 3.11 or later.

```sh
uv add browser-use
```

```python
import asyncio
from browser_use import Agent, Browser

async def main():
    async with await Agent.create(
        model="openai/gpt-6-luna",
        browser=Browser.chrome(),
        workspace="./work",
    ) as agent:
        result = await agent.run("Read my dashboard.")
        print(result.status, result.text)

asyncio.run(main())
```

Omit `browser` to create a Cloud browser.
Chrome discovery uses the application machine.
An application on another machine needs an explicit Chrome endpoint.

Use Pydantic models through `schema=YourModel` for structured output.
Use `Tool` for typed Python callbacks.
Use `events()` for a stream of observations.
Before-tool and after-tool callbacks operate on full tool calls.
A JavaScript tool call can execute several browser operations.

Session methods include `run`, `follow_up`, `execute`, `execute_json`, `events`, `pause`, `resume`, `steer`, `cancel`, and `close`.
A browser-only session can omit `model` and use deterministic execution.
An agent run requires a model.

`run` starts a new transcript while preserving browser and workspace state.
`follow_up` continues the existing transcript.
History restoration does not restore browser login or JavaScript bindings.
A local profile or Cloud profile preserves login independently.

Use `telemetry=False` or the documented environment controls to disable product telemetry.
Never store task secrets inside source examples.
