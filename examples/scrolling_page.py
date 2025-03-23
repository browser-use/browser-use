# Goal: Automates webpage scrolling with various scrolling actions and text search functionality.

import os
import sys
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_openai import ChatOpenAI
from browser_use import Agent
from browser_use.utils import BrowserSessionManager, with_error_handling
from browser_use.browser.browser import Browser, BrowserConfig
"""
Example: Using the 'Scroll down' action.

This script demonstrates how the agent can navigate to a webpage and scroll down the content.
If no amount is specified, the agent will scroll down by one page height.
"""

llm = ChatOpenAI(model='gpt-4o')

agent = Agent(
	# task="Navigate to 'https://en.wikipedia.org/wiki/Internet' and scroll down by one page - then scroll up by 100 pixels - then scroll down by 100 pixels - then scroll down by 10000 pixels.",
	task="Navigate to 'https://en.wikipedia.org/wiki/Internet' and scroll to the string 'The vast majority of computer'",
	llm=llm,
	browser=Browser(config=BrowserConfig(headless=False)),
)

async def main():
    async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
        await managed_agent.run()

@with_error_handling()
async def run_script():
    await main()

if __name__ == "__main__":
    run_script()