"""
Quickstart Example

This is the simplest way to use Browser Use- capable of any web task,
with minimal configuration.
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, Browser, ChatBrowserUse

load_dotenv()


async def main():
	browser = Browser(use_cloud=False)
	llm = ChatBrowserUse()
	task = 'Find the number of stars of the browser-use repository on GitHub'
	agent = Agent(
		browser=browser,
		task=task,
		llm=llm,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
