# Desearch web search

Add web search results to a Browser Use agent with [Desearch](https://desearch.ai/docs).
The action returns up to five titles, links, and snippets using the web search API.
It uses the existing HTTP client dependency.

From the repository root:

```bash
uv sync
export DESEARCH_API_KEY=your-key
export BROWSER_USE_API_KEY=your-browser-use-key
```

Register the action on the tools passed to your agent:

```python
import asyncio

from browser_use import Agent, ChatBrowserUse, Tools
from browser_use.integrations.desearch import register_desearch_actions

async def main():
    tools = Tools()
    register_desearch_actions(tools)
    agent = Agent(
        task='Use desearch_search to find the Browser Use documentation, then open a result.',
        llm=ChatBrowserUse(),
        tools=tools,
    )
    await agent.run()

asyncio.run(main())
```

Save the snippet as `desearch_agent.py` and run `uv run desearch_agent.py` from the repository root.
The search action itself requires only `DESEARCH_API_KEY`; the agent also requires
`BROWSER_USE_API_KEY` and a browser. `query` is required; `limit` defaults to five
and accepts values from one to five. The action caps returned results locally
because the service may return more results than requested.
