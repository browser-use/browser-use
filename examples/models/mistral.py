"""
Simple agent run with Mistral.

You need to set MISTRAL_API_KEY in your environment (and optionally MISTRAL_BASE_URL).
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.llm.mistral import ChatMistral

load_dotenv()

llm = ChatMistral(model='mistral-small-2506', temperature=0.6)
agent = Agent(
	llm=llm,
	task='List two fun weekend activities in Barcelona.',
)


async def main():
	await agent.run(max_steps=10)
	input('Press Enter to continue...')


asyncio.run(main())
