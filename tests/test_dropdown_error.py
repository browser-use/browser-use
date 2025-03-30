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
# browser = Browser(config=BrowserConfig(headless=False))

agent = Agent(
	task=('go to https://codepen.io/shyam-king/pen/emOyjKm and select number "4" and return the output of "selected value"'),
	llm=llm,
	browser_context=BrowserContext(
		browser=Browser(config=BrowserConfig(headless=False, disable_security=True)),
	),
)


async def test_dropdown():
	history: AgentHistoryList = await agent.run(20)
	# await controller.browser.close(force=True)

	result = history.final_result()
	assert result is not None
	assert '4' in result
	print(result)

	# await browser.close()
