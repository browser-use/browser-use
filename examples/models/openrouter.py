"""Simple OpenRouter example.

@dev You need to add OPENROUTER_API_KEY to your environment variables.
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatOpenRouter

load_dotenv()

llm = ChatOpenRouter(
	# model='x-ai/grok-4',
	model='deepcogito/cogito-v2.1-671b',
	api_key=os.getenv('OPENROUTER_API_KEY'),
)
agent = Agent(
	task='Find the number of stars of the browser-use repo',
	llm=llm,
	use_vision=False,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
