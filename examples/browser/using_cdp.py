"""
Simple demonstration of the CDP feature.

To test this locally, follow these steps:
1. Find the chrome executable file.
2. On mac by default, the chrome is in `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
3. Add the following argument to the shortcut:
   `--remote-debugging-port=9222`
4. Open a web browser and navigate to `http://localhost:9222/json/version` to verify that the Remote Debugging Protocol (CDP) is running.
5. Launch this example.

Full command Mac:
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222

@dev You need to set the `OPENAI_API_KEY` environment variable before proceeding.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, Tools
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI

browser_session = BrowserSession(browser_profile=BrowserProfile(cdp_url='http://localhost:9222', is_local=True))
tools = Tools()


async def main():
	agent = Agent(
		task='Visit https://duckduckgo.com and search for "browser-use founders"',
		llm=ChatOpenAI(model='gpt-4.1-mini'),
		tools=tools,
		browser_session=browser_session,
	)

	await agent.run()
	await browser_session.kill()

	input('Press Enter to close...')


if __name__ == '__main__':
	asyncio.run(main())
