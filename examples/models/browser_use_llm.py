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

from browser_use import Agent
from browser_use.llm import ChatBrowserUse


async def main():
	# Create agent with ChatBrowserUse cloud service
	# API key and base URL are loaded from environment variables:
	# - BROWSER_USE_API_KEY (required)
	# - BROWSER_USE_API_URL (optional, defaults to production)
	agent = Agent(
		task='Find the number of stars of the browser-use repo',
		llm=ChatBrowserUse(fast=True),  # fast=True uses gemini-flash-lite, fast=False uses gemini-flash
		flash_mode=True,
	)

	# Run the agent
	result = await agent.run()
	print(f'Result: {result}')


if __name__ == '__main__':
	asyncio.run(main())
