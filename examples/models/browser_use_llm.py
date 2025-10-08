"""
Example usage of ChatBrowserUse with the llm-use cloud service.

This demonstrates how to use the ChatBrowserUse client to connect to the
llm-use cloud service deployed on Railway.

Production URL: https://llm-use-production.up.railway.app

Setup:
1. Get your API key from https://cloud.browser-use.com/dashboard/api
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
"""

import asyncio
import os

from dotenv import load_dotenv
from lmnr import Laminar

from browser_use import Agent
from browser_use.llm import ChatBrowserUse

load_dotenv()

if not os.getenv('BROWSER_USE_API_KEY'):
	raise ValueError('BROWSER_USE_API_KEY is not set')

Laminar.initialize()


async def main():
	# Create agent with ChatBrowserUse cloud service
	# API key and base URL are loaded from environment variables:
	# - BROWSER_USE_API_KEY (required)
	# - BROWSER_USE_LLM_URL (optional, defaults to production)
	agent = Agent(
		task='Find the number of stars of the browser-use repo',
		llm=ChatBrowserUse(base_url='http://0.0.0.0:8000'),
		flash_mode=True,
	)

	# Run the agent
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
