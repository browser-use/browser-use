"""
Example usage of ChatBrowserUse with the llm-use cloud service.

This demonstrates how to use the ChatBrowserUse client to connect to the
llm-use cloud service deployed on Railway.

Production URL: https://llm-use-production.up.railway.app
"""

import asyncio
import os

from browser_use import Agent
from browser_use.llm import ChatBrowserUse


async def main():
	# Create agent with ChatBrowserUse
	# Uses production URL by default, or set BROWSER_USE_API_URL for local testing
	agent = Agent(
		task='Find the number of stars of the browser-use repo',
		llm=ChatBrowserUse(
			super_fast=True,
			base_url=os.getenv('BROWSER_USE_API_URL', 'https://llm-use-production.up.railway.app'),
			api_key=os.getenv('BROWSER_USE_API_KEY', '12345678'),
		),
		flash_mode=True,
	)

	# Run the agent
	result = await agent.run()
	print(f'Result: {result}')


if __name__ == '__main__':
	asyncio.run(main())
