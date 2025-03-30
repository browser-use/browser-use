"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_openai import ChatOpenAI

from browser_use import Agent, AgentHistoryList

llm = ChatOpenAI(model='gpt-4o')

agent = Agent(
	task=('go to google.com and search for text "hi there"'),
	llm=llm,
	browser_context=BrowserContext(
		browser=Browser(config=BrowserConfig(headless=False, disable_security=True)),
	),
	generate_gif='./google.gif',
)


async def test_gif_path():
	if os.path.exists('./google.gif'):
		os.unlink('./google.gif')

	history: AgentHistoryList = await agent.run(20)

	result = history.final_result()
	assert result is not None

	assert os.path.exists('./google.gif'), 'google.gif was not created'
