import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.llm import ChatOpenAI


async def main():
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			keep_alive=True,
			user_data_dir=None,
			headless=False,
		)
	)
	await browser_session.start()

	current_agent = None
	llm = ChatOpenAI(model='gpt-4o')

	task1 = 'find todays weather on San Francisco and extract it as json'
	task2 = 'find todays weather in Zurich and extract it as json'

	agent1 = Agent(
		task=task1,
		browser_session=browser_session,
		llm=llm,
	)
	agent2 = Agent(
		task=task2,
		browser_session=browser_session,
		llm=llm,
	)

	await asyncio.gather(agent1.run(), agent2.run())
	await browser_session.kill()


asyncio.run(main())
