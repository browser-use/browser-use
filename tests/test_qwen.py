import asyncio

import pytest
from langchain_ollama import ChatOllama

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList
from browser_use.browser.browser import Browser, BrowserConfig


@pytest.fixture
def llm():
	"""Initialize language model for testing"""

	# return ChatAnthropic(model_name='claude-3-5-sonnet-20240620', timeout=25, stop=None)
	# NOTE: Make sure to run ollama server with `ollama start'
	return ChatOllama(
		model='qwen2.5:latest',
		num_ctx=128000,
	)


@pytest.fixture(scope='session')
def event_loop():
	"""Create an instance of the default event loop for each test case."""
	loop = asyncio.get_event_loop_policy().new_event_loop()
	yield loop
	loop.close()


@pytest.fixture(scope='session')
async def browser(event_loop):
	browser_instance = Browser(
		config=BrowserConfig(
			headless=True,
		)
	)
	yield browser_instance
	await browser_instance.close()


@pytest.fixture
async def context(browser):
	async with await browser.new_context() as context:
		yield context


# pytest tests/test_qwen.py -v -k "test_qwen_url" --capture=no
# @pytest.mark.asyncio
async def test_qwen_url(llm, context):
	"""Test complex ecommerce interaction sequence"""
	agent = Agent(
		task='go_to_url amazon.com',
		llm=llm,
	)

	history: AgentHistoryList = await agent.run(max_steps=3)

	# Verify sequence of actions
	action_sequence = []
	for action in history.model_actions():
		action_name = list(action.keys())[0]
		if action_name in ['go_to_url', 'open_tab']:
			action_sequence.append('navigate')

	assert 'navigate' in action_sequence  # Navigated to Amazon
