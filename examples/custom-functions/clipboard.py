import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import pyperclip
from langchain_openai import ChatOpenAI
from playwright.async_api import Page

from browser_use import Agent, Controller
from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserProfile, BrowserSession

browser_profile = BrowserProfile(
	headless=False,
)
controller = Controller()


@controller.registry.action('Copy text to clipboard')
def copy_to_clipboard(text: str):
	pyperclip.copy(text)
	return ActionResult(extracted_content=text)


@controller.registry.action('Paste text from clipboard')
async def paste_from_clipboard(page: Page):
	text = pyperclip.paste()
	# send text to browser
	await page.keyboard.type(text)

	return ActionResult(extracted_content=text)


async def main():
	task = 'Copy the text "Hello, world!" to the clipboard, then go to google.com and paste the text'
	model = ChatOpenAI(model='gpt-4o')
	browser_session = BrowserSession(browser_profile=browser_profile)
	await browser_session.start()
	agent = Agent(
		task=task,
		llm=model,
		controller=controller,
		browser_session=browser_session,
	)

	await agent.run()
	await browser_session.stop()

	input('Press Enter to close...')


if __name__ == '__main__':
	asyncio.run(main())
