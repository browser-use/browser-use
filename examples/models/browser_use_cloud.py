"""
Example usage of ChatBrowserUse with the llm-use cloud service.

This demonstrates how to use the ChatBrowserUse client to connect to the
llm-use cloud service deployed on Railway.

Production URL: https://llm-use-production.up.railway.app

Setup:
1. Get your API key from https://cloud.browser-use.com/dashboard/api
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
3. Run this example: python examples/models/browser_use_cloud.py
"""

import asyncio
import os

from browser_use import Agent
from browser_use.llm import ChatBrowserUse


async def main():
	# Get API key from environment
	api_key = os.getenv('BROWSER_USE_API_KEY')
	if not api_key:
		raise ValueError(
			'BROWSER_USE_API_KEY environment variable not set. '
			'Get your key at https://cloud.browser-use.com/dashboard/api'
		)

	# Create agent with ChatBrowserUse cloud service
	agent = Agent(
		task='Find the number of stars of the browser-use repo',
		llm=ChatBrowserUse(
			super_fast=True,  # Use gemini-flash-lite-latest for speed
			base_url=os.getenv('BROWSER_USE_API_URL', 'https://llm-use-production.up.railway.app'),
			api_key=api_key,
		),
		flash_mode=True,
	)

	# Run the agent
	result = await agent.run()
	print(f'Result: {result}')


if __name__ == '__main__':
	asyncio.run(main())
