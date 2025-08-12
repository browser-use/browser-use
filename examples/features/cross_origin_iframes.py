"""
Example of how it supports cross-origin iframes.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, Controller
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI

if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set. Please add it to your environment variables.')


browser_profile = BrowserProfile(
	executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
)
browser_session = BrowserSession(browser_profile=browser_profile)
controller = Controller()


async def main():
	agent = Agent(
		task='Click "Go cross-site (simple page)" button on https://csreis.github.io/tests/cross-site-iframe.html then tell me the text within',
		llm=ChatOpenAI(model='gpt-4.1', temperature=0.0),
		controller=controller,
		browser_session=browser_session,
	)

	await agent.run()
	await browser_session.kill()

	input('Press Enter to close...')


if __name__ == '__main__':
	try:
		asyncio.run(main())
	except Exception as e:
		print(e)
