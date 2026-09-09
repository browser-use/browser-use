# Python

A thin client over the same Node engine. Requires Python 3.11+, Node 22.19+ and Chrome. No PyPI release yet.

```sh
npm run build:python
uv build python --wheel --out-dir artifacts/python
uv venv
uv pip install artifacts/python/browser_use_next-0.1.0-py3-none-any.whl
export OPENROUTER_API_KEY=...
```

```python
import asyncio
from browser_use_next import BrowserUse

async def main():
    async with await BrowserUse.create(
        model='openrouter/openai/gpt-5.6-luna',
        workspace='./work',
    ) as agent:
        result = await agent.run('Find the top story on Hacker News.')
        print(result.status, result.text)
        await agent.follow_up('Summarize the comments.')

asyncio.run(main())
```

The wheel bundles the JS engine. Use `schema=YourPydanticModel` for typed output, `Tool` for Python callbacks, and `browser={'profileDir': './profiles/work'}` for login persistence.

Session methods include `events`, `pause`, `resume`, `steer`, `cancel`, `execute`, `files`, `history`, `save_history`, and `export_recording`. JS option names such as `timeoutMs` remain unchanged. Python hook functions are not serialized; use custom tools and the event/control API.

Custom tools validate input/output with Pydantic. Async callbacks are cancelled with the run. Synchronous callbacks run in a thread and must cooperate with cancellation. Recursive/external schema references fail explicitly.

Use `node='/path/to/node'` to choose the runtime. This is a separate client, not a drop-in replacement for `browser_use.beta.Agent`. The [client source](https://github.com/browser-use/browser-use-js/tree/main/python/browser_use_next) is the complete bridge contract.

For limited runs, `result.partial` exposes the latest published checkpoint as a dictionary with `path` and `value`. It is unvalidated partial data; `result.output` remains reserved for completed results. Enable interaction highlights with `highlightActions=True` on creation.

Browser options are plain dictionaries: `browser={"kind": "cloud", "apiKey": "..."}`, `{"kind": "chromium", "profileDir": "./profile"}`, or `{"kind": "chrome"}`. `allowedDomains`, `prohibitedDomains`, `sensitiveData`, and `telemetry=False` use the same contract as JavaScript. See [sessions](./sessions.md).
