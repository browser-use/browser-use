"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys
from pprint import pprint

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from langchain_openai import ChatOpenAI

from browser_use import Agent, AgentHistoryList, BrowserSession, Controller

llm = ChatOpenAI(model='gpt-4o')
controller = Controller()

# use this test to ask the model questions about the page like
# which color do you see for bbox labels, list all with their label
# what's the smallest bboxes with labels and


@controller.registry.action(description='explain what you see on the screen and ask user for input')
async def explain_screen(text: str) -> str:
	pprint(text)
	answer = input('\nuser input next question: \n')
	return answer


@controller.registry.action(description='done')
async def done(text: str) -> str:
	# pprint(text)
	return 'call explain_screen'


@pytest.mark.skip(reason='this is for local testing only')
async def test_vision():
	browser_session = BrowserSession(headless=True, user_data_dir=None)
	await browser_session.start()
	try:
		agent = Agent(
			task='call explain_screen all the time the user asks you questions e.g. about the page like bbox which you see are labels  - your task is to explain it and get the next question',
			llm=llm,
			controller=controller,
			browser_session=browser_session,
		)
		history: AgentHistoryList = await agent.run(20)
	finally:
		# Make sure to close the browser
		await browser_session.stop()
