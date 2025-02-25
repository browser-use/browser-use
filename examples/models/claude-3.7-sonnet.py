import os
import sys

from langchain_anthropic import ChatAnthropic

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from browser_use import Agent

llm = ChatAnthropic(model_name='claude-3-7-sonnet-20250219', temperature=0.0, timeout=30, stop=None)

agent = Agent(
	task='Go to amazon.com, search for laptop, sort by best rating, and give me the price of the first result',
	llm=llm,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
