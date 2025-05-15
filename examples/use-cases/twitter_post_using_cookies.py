# Goal: Automates posting on X (Twitter) using stored authentication cookies.

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))


browser = Browser(
	config=BrowserConfig(
		# browser_binary_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	)
)
file_path = os.path.join(os.path.dirname(__file__), 'twitter_cookies.txt')
context = BrowserContext(browser=browser, config=BrowserContextConfig(cookies_file=file_path))


async def main():
	agent = Agent(
		browser_context=context,
		task=('go to https://x.com. write a new post with the text "browser-use ftw", and submit it'),
		llm=llm,
		max_actions_per_step=4,
	)
	await agent.run(max_steps=25)
	input('Press Enter to close the browser...')


if __name__ == '__main__':
	asyncio.run(main())
