"""
Example of the fastest + smartest LLM for browser automation.

Setup:
1. Get your API key from https://cloud.browser-use.com/dashboard/api
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatBrowserUse

load_dotenv()

if not os.getenv('BROWSER_USE_API_KEY'):
	raise ValueError('BROWSER_USE_API_KEY is not set')


async def main():
	agent = Agent(
		task='Find the number of stars of the browser-use repo',
		llm=ChatBrowserUse(),
	)

	# Run the agent
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
