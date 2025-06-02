import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')
llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))
browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		downloads_dir='~/Downloads',
		user_data_dir='~/.config/browseruse/profiles/default',
	)
)


async def run_download():
	agent = Agent(
		task=('Go to "https://file-examples.com/" and download the smallest doc file.'),
		llm=llm,
		max_actions_per_step=8,
		use_vision=True,
		browser_session=browser_session,
	)
	await agent.run(max_steps=25)
	await browser_session.close()


if __name__ == '__main__':
	asyncio.run(run_download())
