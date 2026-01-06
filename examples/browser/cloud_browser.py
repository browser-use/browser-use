"""
Examples of using Browser-Use cloud browser service.

Prerequisites:
1. Set BROWSER_USE_API_KEY environment variable
2. Active subscription at https://cloud.browser-use.com
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, Browser, ChatBrowserUse

load_dotenv()


async def basic():
	"""Simplest usage - just pass cloud params directly."""
	browser = Browser(use_cloud=True)

	agent = Agent(
		task='Go to github.com/browser-use/browser-use and tell me the star count',
		llm=ChatBrowserUse(),
		browser=browser,
	)

	result = await agent.run()
	print(f'Result: {result}')


async def full_config():
	"""Full cloud configuration with specific profile."""
	browser = Browser(
		# cloud_profile_id='21182245-590f-4712-8888-9611651a024c',
		cloud_proxy_country_code='jp',
		cloud_timeout=60,
	)

	agent = Agent(
		task='go and check my ip address and the location',
		llm=ChatBrowserUse(),
		browser=browser,
	)

	result = await agent.run()
	print(f'Result: {result}')


async def main():
	try:
		# await basic()
		await full_config()
	except Exception as e:
		print(f'Error: {e}')


if __name__ == '__main__':
	asyncio.run(main())
