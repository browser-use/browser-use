import os

# Optional: Disable telemetry
# os.environ["ANONYMIZED_TELEMETRY"] = "false"

# Optional: Set the OLLAMA host to a remote server
# os.environ["OLLAMA_HOST"] = "http://x.x.x.x:11434"

import asyncio
from browser_use import Agent
from langchain_ollama import ChatOllama
from browser_use.utils import BrowserSessionManager, with_error_handling


async def run_search() -> str:
    agent = Agent(
        task="Search for a 'browser use' post on the r/LocalLLaMA subreddit and open it.",
        llm=ChatOllama(
            model="qwen2.5:32b-instruct-q4_K_M",
            num_ctx=32000,
        ),
    )

    result = await agent.run()
    return result


@with_error_handling()
async def run_script():
    agent = Agent(
        task="Search for a 'browser use' post on the r/LocalLLaMA subreddit and open it.",
        llm=ChatOllama(
            model="qwen2.5:32b-instruct-q4_K_M",
            num_ctx=32000,
        ),
    )
    async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
        result = await managed_agent.run()
        print("\n\n", result)

if __name__ == "__main__":
    run_script()