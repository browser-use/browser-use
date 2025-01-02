import os
import sys

from browser_use.browser.browser import Browser, BrowserConfig

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from langchain_openai import ChatOpenAI

from browser_use import Agent

"""
Example: Using the 'Scroll down' action.

This script demonstrates how the agent can navigate to a webpage and scroll down the content.
If no amount is specified, the agent will scroll down by one page height.
"""

llm = ChatOpenAI(model='gpt-4o')

agent = Agent(
	# task="Navigate to 'https://en.wikipedia.org/wiki/Internet' and scroll down by one page - then scroll up by 100 pixels - then scroll down by 100 pixels - then scroll down by 10000 pixels.",
	task="Navigate to 'https://en.wikipedia.org/wiki/Internet' and to the string 'The vast majority of computer'",
	llm=llm,
	browser=Browser(config=BrowserConfig(headless=False)),
)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
