import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use.agent.service import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI

browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		keep_alive=True,
		headless=False,
		record_video_dir='./tmp/recordings',
		user_data_dir='~/.config/browseruse/profiles/default',
	)
)
llm = ChatOpenAI(model='gpt-4.1')


async def main():
	await browser_session.start()
	agents = [
		Agent(task=task, llm=llm, browser_session=browser_session)
		for task in [
			'Search Google for weather in Tokyo',
			'Check Reddit front page title',
			'Look up Bitcoin price on Coinbase',
			'Find NASA image of the day',
			'Check top story on CNN',
			# 'Search latest SpaceX launch date',
			# 'Look up population of Paris',
			# 'Find current time in Sydney',
			# 'Check who won last Super Bowl',
			# 'Search trending topics on Twitter',
		]
	]

	print(await asyncio.gather(*[agent.run() for agent in agents]))
	await browser_session.kill()


if __name__ == '__main__':
	asyncio.run(main())
