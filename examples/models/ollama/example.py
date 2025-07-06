"""
Example script showing how to use Ollama with browser-use
"""
import asyncio
import os
from browser_use import Agent, Browser, BrowserConfig
from browser_use.llm.ollama import BrowserUseOllama  # Use this wrapper instead of ChatOllama
from browser_use.agent.views import AgentHistoryList

# Optional: Disable telemetry
os.environ["ANONYMIZED_TELEMETRY"] = "false"

# Optional: Set the OLLAMA host
os.environ["OLLAMA_HOST"] = "http://localhost:11434"

config = BrowserConfig(
    headless=False,
    disable_security=True,
)
browser = Browser(config=config)

async def run_search() -> AgentHistoryList:
    agent = Agent(
        task="Navigate to www.example.com and describe what you see on the page",
        llm=BrowserUseOllama(  # Use BrowserUseOllama instead of ChatOllama
            model='llama3',  # Use any Ollama model you have available
            num_ctx=32000,
        ),
        browser=browser,
        use_vision=True,  # Set to False if your model doesn't support vision
        tool_calling_method="function_calling",
    )

    result = await agent.run()
    return result

async def main():
    result = await run_search()
    print('\n\n', result)

if __name__ == '__main__':
    asyncio.run(main())
