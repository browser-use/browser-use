"""
Simple agent run using Mistral via the OpenAI-compatible API.

Requires MISTRAL_API_KEY in your environment.

Usage:
  export MISTRAL_API_KEY=your_key
  python examples/models/mistral.py
"""

import asyncio
import os

from browser_use import Agent, ChatMistral


async def main() -> None:
	if not os.getenv('MISTRAL_API_KEY'):
		print('Make sure you have MISTRAL_API_KEY set, e.g.:')
		print('  export MISTRAL_API_KEY=your_key')
		return

	llm = ChatMistral(
		# Defaults to "mistral-medium-latest" and base_url https://api.mistral.ai/v1
		# model="mistral-medium-latest",
	)

	agent = Agent(
		task='Go to example.com, click the first link, and return the page title.',
		llm=llm,
	)

	await agent.run(max_steps=10)
	input('Press Enter to continue...')


if __name__ == '__main__':
	asyncio.run(main())
