"""
Use Obscura as a layout-free CDP backend for browser-use.

Obscura (https://github.com/h4ckf0r0day/obscura) is a lightweight headless
browser written in Rust. It runs real JavaScript via V8 and speaks the Chrome
DevTools Protocol, but it has no layout or paint engine, which keeps it fast and
light for text and DOM driven automation. It cannot take screenshots, so run the
agent with use_vision=False.

To run this example:
1. Build obscura (see its README) and start its CDP server:
   obscura serve --port 9222
2. Verify it is up by opening http://localhost:9222/json/version
3. Set the OPENAI_API_KEY environment variable.
4. Launch this example.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI

# Obscura serves the CDP endpoint and /json/version just like headless Chrome.
browser_session = BrowserSession(browser_profile=BrowserProfile(cdp_url='http://localhost:9222', is_local=True))


async def main():
	agent = Agent(
		task='Go to https://news.ycombinator.com and report the titles of the top 5 stories',
		llm=ChatOpenAI(model='gpt-4.1-mini'),
		browser_session=browser_session,
		# Obscura has no paint engine and cannot take screenshots, so drive the
		# agent over the DOM only.
		use_vision=False,
	)

	await agent.run()
	await browser_session.kill()


if __name__ == '__main__':
	asyncio.run(main())
