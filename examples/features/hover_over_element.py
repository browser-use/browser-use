import asyncio
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.browser.browser import Browser

load_dotenv()
if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set. Please add it to your environment variables.')


async def run_hover():
	browser = Browser()
	llm = ChatOpenAI(model='gpt-4o')
	agent = Agent(
		task='Go to "https://en.wikipedia.org/wiki/Main_Page", hover over Wikipedia link in the middle and change '
		'the page preview setting.',
		llm=llm,
		max_actions_per_step=1,
		use_vision=True,
		browser=browser,
	)
	await agent.run(max_steps=5)
	await browser.close()


if __name__ == '__main__':
	asyncio.run(run_hover())
