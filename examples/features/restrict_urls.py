import os
import sys

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from browser_use.browser.context import BrowserContextConfig

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import argparse
import asyncio

from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.controller.service import Controller

llm = ChatOpenAI(model='gpt-4o', temperature=0.0)
task = (
	'go to google.com and search for openai.com and click on the first link then extract content and scroll down - whats there?'
)

allowed_domains = ['google.com']

browser = Browser(
	config=BrowserConfig(
		chrome_instance_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		new_context_config=BrowserContextConfig(
			allowed_domains=allowed_domains,
		),
	),
)

agent = Agent(
	task=task,
	llm=llm,
	browser=browser,
)


async def main():
	await agent.run(max_steps=25)

	input('Press Enter to close the browser...')
	await browser.close()


asyncio.run(main())
