## Check the weather near Chungnbuk National University using browser-use.

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
    "Go to https://www.kma.go.kr/cheongju and summarize the current weather near Chungbuk National University in Korea, "
    "including temperature, precipitation probability, humidity, wind, cloud cover, and general conditions. "
    "Present the information clearly in the terminal."
)

    llm = ChatOpenAI(model="gpt-4o", temperature=0.0)
    
    agent = Agent(task=task, llm=llm)
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())