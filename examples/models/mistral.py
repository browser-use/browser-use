"""
Simple Mistral AI example for browser-use.
@dev Add MISTRAL_API_KEY to your environment variables.
"""

import asyncio
import os

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm import ChatMistral

api_key = os.getenv('MISTRAL_API_KEY', '')
if not api_key:
	raise ValueError('MISTRAL_API_KEY is not set')


async def main():
	llm = ChatMistral(model='mistral-small-latest', api_key=api_key, temperature=0.0)

	agent = Agent(
		task='Go to amazon.com, search for laptop, sort by best rating, and give me the price of the first result',
		llm=llm,
	)

	await agent.run(max_steps=10)


if __name__ == '__main__':
	asyncio.run(main())
