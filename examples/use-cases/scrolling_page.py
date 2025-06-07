# Goal: Automates webpage scrolling with various scrolling actions and text search functionality.

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession

if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set')

"""
Example: Using the 'Scroll down' action.

This script demonstrates how the agent can navigate to a webpage and scroll down the content.
If no amount is specified, the agent will scroll down by one page height.
"""

llm = ChatOpenAI(model='gpt-4o')

browser_profile = BrowserProfile(headless=False)
browser_session = BrowserSession(browser_profile=browser_profile)

agent = Agent(
	# task="Navigate to 'https://en.wikipedia.org/wiki/Internet' and scroll down by one page - then scroll up by 100 pixels - then scroll down by 100 pixels - then scroll down by 10000 pixels.",
	task="Navigate to 'https://en.wikipedia.org/wiki/Internet' and scroll to the string 'The vast majority of computer'",
	llm=llm,
	browser_session=browser_session,
)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
