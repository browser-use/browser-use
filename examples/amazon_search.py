"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys
from browser_use.utils import BrowserSessionManager, with_error_handling

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from langchain_openai import ChatOpenAI

from browser_use import Agent

llm = ChatOpenAI(model='gpt-4o')
agent = Agent(
	task='Go to amazon.com, search for laptop, sort by best rating, and give me the price of the first result',
	llm=llm,
)


async def main():
    async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
        await managed_agent.run()

@with_error_handling()
async def run_script():
    await main()

if __name__ == "__main__":
    run_script()
