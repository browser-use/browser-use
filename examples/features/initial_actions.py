import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI

from browser_use import Agent, BrowserSession

llm = ChatOpenAI(model='gpt-4o')

browser_session = BrowserSession()


async def main():
	await browser_session.start()
	agent = Agent(
		task='What theories are displayed on the page?',
		initial_actions=[
			{'open_tab': {'url': 'https://www.google.com'}},
			{'open_tab': {'url': 'https://en.wikipedia.org/wiki/Randomness'}},
			{'scroll_down': {'amount': 1000}},
		],
		llm=llm,
		browser_session=browser_session,
	)
	await agent.run(max_steps=10)


if __name__ == '__main__':
	asyncio.run(main())
