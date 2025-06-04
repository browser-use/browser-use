"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys
import time

import pytest

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.dom.service import DomService

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from langchain_openai import ChatOpenAI

from browser_use import Agent

llm = ChatOpenAI(model='gpt-4o')


@pytest.mark.skip(reason='this is for local testing only')
async def test_svg_button():
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=False,
			disable_security=True,
			keep_alive=True,
		)
	)

	await browser_session.start()

	agent = Agent(
		task=('click the edit icon for the short bio section on the profile page'),
		llm=llm,
		browser_session=browser_session,
		validate_output=False,
		max_failures=1,
	)

	page = await agent.browser_context.new_page()
	await page.goto(f'https://tarasyarema.com/random-pages/button.html?seed={int(time.time())}')

	try:
		res = await agent.run(3)
		assert res.is_successful, 'Agent failed to complete the task.'

		dom_service = DomService(page)
		state = await dom_service.get_clickable_elements(
			highlight_elements=True,
		)

		for k, v in state.selector_map.items():
			print(f'{k}: {v}')

		input('Press Enter to continue...')

	finally:
		await browser_session.stop()


if __name__ == '__main__':
	asyncio.run(test_svg_button())
