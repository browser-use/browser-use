"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import shutil
import sys

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_openai import ChatOpenAI

from browser_use import Agent, AgentHistoryList

llm = ChatOpenAI(model='gpt-4o')


async def test_save_conversation_contains_slash():
	if os.path.exists('./logs'):
		shutil.rmtree('./logs')

	agent = Agent(
		task=('go to google.com and search for text "hi there"'),
		llm=llm,
		browser_context=BrowserContext(
			browser=Browser(config=BrowserConfig(headless=False, disable_security=True)),
		),
		save_conversation_path='logs/conversation',
	)
	history: AgentHistoryList = await agent.run(20)

	result = history.final_result()
	assert result is not None

	assert os.path.exists('./logs'), 'logs directory was not created'
	assert os.path.exists('./logs/conversation_2.txt'), 'logs file was not created'


async def test_save_conversation_not_contains_slash():
	if os.path.exists('./logs'):
		shutil.rmtree('./logs')

	agent = Agent(
		task=('go to google.com and search for text "hi there"'),
		llm=llm,
		browser_context=BrowserContext(
			browser=Browser(config=BrowserConfig(headless=False, disable_security=True)),
		),
		save_conversation_path='logs',
	)
	history: AgentHistoryList = await agent.run(20)

	result = history.final_result()
	assert result is not None

	assert os.path.exists('./logs'), 'logs directory was not created'
	assert os.path.exists('./logs/_2.txt'), 'logs file was not created'


async def test_save_conversation_deep_directory():
	if os.path.exists('./logs'):
		shutil.rmtree('./logs')

	agent = Agent(
		task=('go to google.com and search for text "hi there"'),
		llm=llm,
		browser_context=BrowserContext(
			browser=Browser(config=BrowserConfig(headless=False, disable_security=True)),
		),
		save_conversation_path='logs/deep/directory/conversation',
	)
	history: AgentHistoryList = await agent.run(20)

	result = history.final_result()
	assert result is not None

	assert os.path.exists('./logs/deep/directory'), 'logs directory was not created'
	assert os.path.exists('./logs/deep/directory/conversation_2.txt'), 'logs file was not created'
