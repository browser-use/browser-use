"""
Example of how it supports cross-origin iframes.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig

# Load environment variables
load_dotenv()
if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set. Please add it to your environment variables.')


browser = Browser(
	config=BrowserConfig(
		browser_binary_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	)
)
controller = Controller()


async def main():
	agent = Agent(
		task='Click "Go cross-site (simple page)" button on https://csreis.github.io/tests/cross-site-iframe.html then tell me the text within',
		llm=ChatOpenAI(model='gpt-4o', temperature=0.0),
		controller=controller,
		browser=browser,
	)

	await agent.run()
	await browser.close()

	input('Press Enter to close...')


if __name__ == '__main__':
	try:
		asyncio.run(main())
	except Exception as e:
		print(e)
