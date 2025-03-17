import os
import sys
from pathlib import Path

from browser_use.agent.views import ActionResult

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from langchain_openai import ChatOpenAI

from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

browser = Browser(config=BrowserConfig(chrome_instance_path='/usr/bin/google-chrome-stable',))

async def main():
	agent = Agent(
		task='Go to www.cnn.com',
		llm=ChatOpenAI(model='gpt-4o'),
		browser=browser,
	)

	await agent.run()
	await browser.close()

	input('Press Enter to close...')


if __name__ == '__main__':
	asyncio.run(main())
