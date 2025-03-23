import os
import sys
from pathlib import Path

from browser_use.agent.views import ActionResult

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from langchain_openai import ChatOpenAI

from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext
from browser_use.utils import BrowserSessionManager, with_error_handling

browser = Browser(
	config=BrowserConfig(
		headless=False,
		# NOTE: you need to close your chrome browser - so that this can open your browser in debug mode
		chrome_instance_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	)
)
controller = Controller()

@with_error_handling()
async def run_script():
	task = f'In docs.google.com write my Papa a quick thank you for everything letter \n - Magnus'
	task += f' and save the document as pdf'
	model = ChatOpenAI(model='gpt-4o')
	agent = Agent(
		task=task,
		llm=model,
		controller=controller,
		browser=browser,
	)
	async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
		await managed_agent.run()
	await browser.close()
	input('Press Enter to close...')

if __name__ == '__main__':
    run_script()
