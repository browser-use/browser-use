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
    async with Agent(
        task="Read my dashboard.",
        workspace="./work",
    ) as agent:
        result = await agent.run()
        print(result.final_result())
        follow_up = await agent.follow_up("Explain the largest change.")
        print(follow_up.final_result())

asyncio.run(main())
```

Python `Agent` defaults to `bu-recommended` through the Browser Use gateway.
Set `BROWSER_USE_API_KEY` for gateway authentication.
Create an API key at https://cloud.browser-use.com/settings?tab=api-keys&new=1.
Pass `model="provider/model"` to select another model.
Omit `browser` to create a Cloud browser.
Pass `browser=Browser.chrome()` to connect to your real Chrome browser.
Chrome discovery uses the application machine.
An application on another machine needs an explicit Chrome endpoint.

`Agent(task="...")` delays startup until `run()` or context entry.
`await Agent.create(...)` starts the session immediately.
Both forms return the same Python client interface.
Use `await agent.close()` when you do not use `async with`.
`run(task)` accepts task text directly and overrides the constructor task for that call.
`result.final_result()` returns completed response text, including JSON text for structured output.
It returns `None` when the task stops without completion.
`result.output` retains structured objects and Pydantic model instances.

Use Pydantic models through `schema=YourModel` for structured output.
The constructor also accepts `output_model_schema=YourModel` for subsequent runs.
Use `Tool` for typed Python callbacks.
Use `events()` for a stream of observations.
Before-tool and after-tool callbacks operate on full tool calls.
A JavaScript tool call can execute several browser operations.

Session methods include `run`, `follow_up`, `execute`, `execute_json`, `events`, `pause`, `resume`, `steer`, `cancel`, and `close`.
`Browser` and `BrowserUse` remain model-free when callers omit `model`.
Their deterministic execution does not call a model.
`Agent` supplies the gateway model when callers omit `model`.

`run` starts a new transcript while preserving browser and workspace state.
`follow_up` continues the existing transcript.
`agent.add_new_task(text)` makes the next `run()` continue the existing transcript.
These methods retain browser, workspace, and JavaScript state within the active session.
History restoration does not restore browser login or JavaScript bindings.
A local profile or Cloud profile preserves login independently.

`Browser(use_cloud=True)` selects Cloud.
`Browser(cdp_url=url)` selects an existing browser connection.
`Browser(use_cloud=False)` selects local Chromium.
Local constructors accept `headless`, `executable_path`, and `user_data_dir`.
Pass an unstarted `Browser` instance to `Agent(browser=...)` as configuration.
Use `Browser.cdp(url)` when another client already owns the connection.

Pi warns when supported obsolete planner settings have no effect.
Unsupported model objects, security controls, and browser settings still raise errors.
Pi rejects `use_vision=False` because it does not support disabling screenshots.
Provider wrapper classes such as `ChatOpenAI` remain unavailable.

Use `telemetry=False` or the documented environment controls to disable product telemetry.
Never store task secrets inside source examples.
