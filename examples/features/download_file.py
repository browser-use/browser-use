import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent
from browser_use.browser import BrowserSession
from browser_use.llm import ChatGoogle

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

assert api_key is not None, 'GOOGLE_API_KEY must be set'
llm = ChatGoogle(model='gemini-2.0-flash-exp', api_key=api_key)

from browser_use.browser import BrowserProfile

browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		downloads_path='~/Downloads',
		user_data_dir='~/.config/browseruse/profiles/default',
	)
)


async def run_download():
	agent = Agent(
		task='Go to "https://file-examples.com/" and download the smallest doc file.',
		llm=llm,
		max_actions_per_step=8,
		use_vision=True,
		browser_session=browser_session,
	)
	await agent.run(max_steps=25)


if __name__ == '__main__':
	asyncio.run(run_download())
