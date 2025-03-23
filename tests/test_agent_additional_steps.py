"""
Testing agent running with additional steps

The agent should ask for more steps when it is approaching the last step (initial max steps defined by user).
"""

import asyncio
import os
from typing import List

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr, BaseModel

from browser_use import Agent, BrowserConfig, ActionResult, Controller
from browser_use.browser.browser import Browser
from browser_use.browser.context import  BrowserContextConfig, BrowserContextWindowSize

load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
	raise ValueError('GEMINI_API_KEY is not set')

controller = Controller()

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))

browser = Browser(
	config=BrowserConfig(
		new_context_config=BrowserContextConfig(
			viewport_expansion=0,			
			no_viewport=False,
			browser_window_size=BrowserContextWindowSize(width=1280, height=1000),

		),
		headless=False,
    )
)

# This task requires 30 steps (10 searches with 20 seconds wait time after each search)
task = """

 Step 1 - Go to google.com
 Step 2 - Search for one
 Step 3 - Go to google.com
 wait 20 seconds
 Step 4 - Search for two
 Step 5 - Go to google.com
 wait 20 seconds
 Step 6 - Search for three
 Step 7 - Go to google.com
 wait 20 seconds
 Step 8 - Search for four
 Step 9 - Go to google.com
 wait 20 seconds
 Step 10 - Search for five
 Step 11 - Go to google.com
 wait 20 seconds
 Step 12 - Search for six
 Step 13 - Go to google.com
 wait 20 seconds
 Step 14 - Search for seven
 Step 15 - Go to google.com
 wait 20 seconds
 Step 16 - Search for eight
 Step 17 - Go to google.com
 wait 20 seconds
 Step 18 - Search for nine
 Step 19 - Go to google.com
 wait 20 seconds
 Step 20 - Search for ten
"""

async def main():
	agent = Agent(
		task=task,
		llm=llm,
		controller=controller,
		max_actions_per_step=1,
		browser=browser,
		use_vision=False,
	)

	await agent.run(max_steps=5)	# max_steps is 5, so agent should ask for more steps 


if __name__ == '__main__':
	asyncio.run(main())