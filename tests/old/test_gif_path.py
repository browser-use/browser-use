"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys

from browser_use.browser import BrowserProfile, BrowserSession

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_use import Agent, AgentHistoryList
from browser_use.llm import ChatOpenAI

llm = ChatOpenAI(model='gpt-4o')

browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, disable_security=True))

agent = Agent(
	task=('go to google.com and search for text "hi there"'),
	llm=llm,
	browser_session=browser_session,
	generate_gif='./google.gif',
)


async def test_gif_path():
	if os.path.exists('./google.gif'):
		os.unlink('./google.gif')

	await browser_session.start()
	try:
		history: AgentHistoryList = await agent.run(20)

		result = history.final_result()
		assert result is not None

		assert os.path.exists('./google.gif'), 'google.gif was not created'
	finally:
		await browser_session.stop()
