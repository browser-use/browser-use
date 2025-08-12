"""
Simple demonstration of the CDP feature.

To test this locally, follow these steps:
1. Create a shortcut for the executable Chrome file.
2. Add the following argument to the shortcut:
   - On Windows: `--remote-debugging-port=9222`
3. Open a web browser and navigate to `http://localhost:9222/json/version` to verify that the Remote Debugging Protocol (CDP) is running.
4. Launch this example.

@dev You need to set the `GOOGLE_API_KEY` environment variable before proceeding.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent, Controller
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatGoogle

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		headless=False,
	),
	cdp_url='http://localhost:9222',
)
controller = Controller()


async def main():
	task = 'In docs.google.com write my Papa a quick thank you for everything letter \n - Magnus'
	task += ' and save the document as pdf'
	# Assert api_key is not None to satisfy type checker
	assert api_key is not None, 'GOOGLE_API_KEY must be set'
	model = ChatGoogle(model='gemini-2.0-flash-exp', api_key=api_key)
	agent = Agent(
		task=task,
		llm=model,
		controller=controller,
		browser_session=browser_session,
	)

	await agent.run()
	await browser_session.kill()

	input('Press Enter to close...')


if __name__ == '__main__':
	asyncio.run(main())
