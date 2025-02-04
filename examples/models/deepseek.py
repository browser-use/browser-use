import asyncio
import os

from dotenv import load_dotenv

from browser_use import LLM, Agent

# dotenv
load_dotenv()

api_key = os.getenv("DEEPSEEK_API_KEY", "")
if not api_key:
    raise ValueError("DEEPSEEK_API_KEY is not set")


async def run_search():
    agent = Agent(
        task=(
            "1. Go to https://www.reddit.com/r/LocalLLaMA "
            "2. Search for 'browser use' in the search bar"
            "3. Click on first result"
            "4. Return the first comment"
        ),
        llm=LLM(model="deepseek/deepseek-chat"),
        use_vision=False,
    )

    await agent.run()


if __name__ == "__main__":
    asyncio.run(run_search())
