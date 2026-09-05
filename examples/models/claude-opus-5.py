"""
Read a public page with Claude Opus 5.

@dev Add ANTHROPIC_API_KEY to your environment or .env file.
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, ChatAnthropic

load_dotenv()

llm = ChatAnthropic(model='claude-opus-5')

agent = Agent(
	task='Visit https://quotes.toscrape.com/ and list the first three quotes with their authors.',
	llm=llm,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
