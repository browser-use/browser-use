"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys

from browser_use.browser import BrowserProfile, BrowserSession

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_openai import ChatOpenAI

from browser_use import Agent, AgentHistoryList

llm = ChatOpenAI(model='gpt-4o')
browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True))

agent = Agent(
	task=('go to https://codepen.io/shyam-king/pen/emOyjKm and select number "4" and return the output of "selected value"'),
	llm=llm,
	browser_session=browser_session,
)


async def test_dropdown():
	await browser_session.start()
	try:
		history: AgentHistoryList = await agent.run(20)

		result = history.final_result()
		assert result is not None
		assert '4' in result
		print(result)
	finally:
		await browser_session.stop()
