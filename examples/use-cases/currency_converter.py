import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from browser_use import Agent

async def main():
    task = (
        "Go to https://www.google.com/search?q=usd+to+krw "
        "and find the current exchange rate from USD to KRW. "
        "Then convert 100 USD to KRW and print only the result as a number."
    )

    llm = ChatOpenAI(model="gpt-4o", temperature=0.0)
    agent = Agent(task=task, llm=llm)
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
