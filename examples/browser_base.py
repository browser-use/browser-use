"""
Simple try of the agent using BrowserBase.

@dev You need to add OPENAI_API_KEY, BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID to your environment variables.
"""

import os
import sys

from browser_use.browser.browser import Browser, BrowserConfig

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


import asyncio

from langchain_openai import ChatOpenAI

from browser_use import Agent


browserbase_api_key = os.getenv('BROWSERBASE_API_KEY')
browserbase_project_id = os.getenv('BROWSERBASE_PROJECT_ID')


browser = Browser(
	config=BrowserConfig(
		browserbase_api_key=browserbase_api_key,
		browserbase_project_id=browserbase_project_id,  
	)
)

llm = ChatOpenAI(model='gpt-4o')
agent = Agent(
	task='Go to amazon.com, search for laptop, sort by best rating, and give me the price of the first result',
	llm=llm,
	browser=browser,
)


async def main():
	await agent.run(max_steps=3)
	agent.create_history_gif()


asyncio.run(main())
