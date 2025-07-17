import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
from lmnr import Laminar

load_dotenv()

Laminar.initialize()


from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatGoogle

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogle(model='gemini-2.5-flash', api_key=api_key)

browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		viewport_expansion=0,
		user_data_dir='~/.config/browseruse/profiles/default',
	)
)


async def run_search():
	agent = Agent(
		task='Go to google.com/travel/flights and find the cheapest flight from New York to Paris on 2025-07-15',
		llm=llm,
		max_actions_per_step=4,
		browser_session=browser_session,
	)

	await agent.run(max_steps=25)


if __name__ == '__main__':
	asyncio.run(run_search())
