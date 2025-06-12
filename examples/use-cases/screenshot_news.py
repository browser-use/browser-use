import os
import sys
import asyncio
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from browser_use.agent.service import Agent

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise EnvironmentError("OPENAI_API_KEY is not set. Please add it to your .env file.")

llm = ChatOpenAI(model="gpt-4o", api_key=api_key)

agent = Agent(
    llm=llm,
    task="Go to https://news.google.com and extract the titles of the top 3 news headlines. Print them.",
)

async def main():
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
