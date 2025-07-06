# Using Ollama with browser-use

To use Ollama with browser-use version 0.4.2 or newer, you need to use the `BrowserUseOllama` wrapper class instead of using `ChatOllama` directly.

## Example Usage

```python
import asyncio
from browser_use import Agent, Browser, BrowserConfig
from browser_use.llm.ollama import BrowserUseOllama  # Use this wrapper instead of ChatOllama
from browser_use.agent.views import AgentHistoryList
import os

# Optional: Disable telemetry
os.environ["ANONYMIZED_TELEMETRY"] = "false"

# Optional: Set the OLLAMA host to a remote server
os.environ["OLLAMA_HOST"] = "http://localhost:11434"

config = BrowserConfig(
    headless=False,
    disable_security=True,
)
browser = Browser(config=config)

async def run_search() -> AgentHistoryList:
    agent = Agent(
        task="Navigate to www.example.com and click on the first link",
        llm=BrowserUseOllama(  # Use BrowserUseOllama instead of ChatOllama
            model='qwen3:14b',
            num_ctx=32000,
        ),
        browser=browser,
        use_vision=False,
        tool_calling_method="function_calling",
    )

    result = await agent.run()
    return result

async def main():
    result = await run_search()
    print('\n\n', result)

if __name__ == '__main__':
    asyncio.run(main())
```

## Why this wrapper is needed

In browser-use version 0.4.2 and newer, the token tracking mechanism attempts to add an `ainvoke` attribute to the LLM object. However, newer versions of langchain-ollama use Pydantic validation that prevents dynamically adding attributes.

The `BrowserUseOllama` wrapper class solves this issue by providing a compatible interface that works with browser-use's token tracking system.
