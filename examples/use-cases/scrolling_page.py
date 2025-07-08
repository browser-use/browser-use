# Goal: Automates webpage scrolling with various scrolling actions and text search functionality.

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI

if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set')

"""
Example: Using the 'Scroll' action with custom page amounts.

This script demonstrates how the agent can navigate to a webpage and scroll by specific page amounts.
The scroll action now supports:
- Scrolling by a specific number of pages using the 'num_pages' parameter (e.g., 0.5 for half page, 1.0 for one page, 2.0 for two pages)
- Scrolling by one page height if no num_pages is specified (default behavior)
- Scrolling up or down using the 'down' parameter
"""

llm = ChatOpenAI(model='gpt-4.1')

browser_profile = BrowserProfile(headless=False)
browser_session = BrowserSession(browser_profile=browser_profile)

agent = Agent(
	task="Navigate to 'https://en.wikipedia.org/wiki/Internet' and scroll down by one page - then scroll up by 0.5 pages - then scroll down by 0.25 pages - then scroll down by 2 pages.",
	# Alternative task to demonstrate text-based scrolling:
	# task="Navigate to 'https://en.wikipedia.org/wiki/Internet' and scroll to the string 'The vast majority of computer'",
	llm=llm,
	browser_session=browser_session,
)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
