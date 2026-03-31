"""Test: agent navigates to wikipedia.org and reports one skill it can read."""

import asyncio

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm.anthropic.chat import ChatAnthropic

llm = ChatAnthropic(model='claude-sonnet-4-20250514')

agent = Agent(
	task='Go to wikipedia.org. Check the domain skills available, pick one, read it with read_skill, and report its contents.',
	llm=llm,
	use_skillbase=True,
)


async def main():
	result = await agent.run(max_steps=5)
	print('\n=== Final result ===')
	print(result.final_result())


asyncio.run(main())
