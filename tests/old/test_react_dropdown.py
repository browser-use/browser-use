"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys

from browser_use.browser import BrowserProfile, BrowserSession

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from browser_use import Agent, AgentHistoryList
from browser_use.llm import ChatOpenAI

llm = ChatOpenAI(model='gpt-4.1')

browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, disable_security=True))

agent = Agent(
	task=(
		'go to https://codepen.io/shyam-king/pen/ByBJoOv and select "Tiger" dropdown and read the text given in "Selected Animal" box (it can be empty as well)'
	),
	llm=llm,
	browser_session=browser_session,
)


async def test_dropdown():
	await browser_session.start()
	try:
		history: AgentHistoryList = await agent.run(10)

		result = history.final_result()
		assert result is not None
		print('result: ', result)
	finally:
		await browser_session.stop()


if __name__ == '__main__':
	asyncio.run(test_dropdown())
