import asyncio
import os
import sys

if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY is not set. Please define it in your .env file.")

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from browser_use import Agent
from langchain_openai import ChatOpenAI

async def main():
    task = (
        "Go to https://coinmarketcap.com/currencies/bitcoin/ "
        "and tell me the current Bitcoin price in USD. "
        "Just the number, no explanation."
    )

    llm = ChatOpenAI(model="gpt-4o", temperature=0.0)
    agent = Agent(task=task, llm=llm)
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
