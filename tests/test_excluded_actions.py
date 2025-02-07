import asyncio
import os

import pytest
from langchain_openai import AzureChatOpenAI
from pydantic import SecretStr

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.controller.service import Controller

# run with:
# python -m pytest tests/test_excluded_actions.py -v -k "test_only_open_tab_allowed" --capture=no


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


@pytest.fixture
def llm():
	"""Initialize language model for testing"""
	return AzureChatOpenAI(
		model='gpt-4o',
		api_version='2024-10-21',
		azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT', ''),
		api_key=SecretStr(os.getenv('AZURE_OPENAI_KEY', '')),
	)


# pytest tests/test_excluded_actions.py -v -k "test_only_open_tab_allowed" --capture=no
@pytest.mark.asyncio
async def test_only_open_tab_allowed(llm, context):
	"""Test that only open_tab action is available while others are excluded"""

	# Create list of all default actions except open_tab
	excluded_actions = [
		'search_google',
		'go_to_url',
		'go_back',
		'click_element',
		'input_text',
		'switch_tab',
		'extract_content',
		'done',
		'scroll_down',
		'scroll_up',
		'send_keys',
		'scroll_to_text',
		'get_dropdown_options',
		'select_dropdown_option',
	]

	# Initialize controller with excluded actions
	controller = Controller(exclude_actions=excluded_actions)

	# Create agent with a task that would normally use other actions
	agent = Agent(
		task="Go to google.com and search for 'python programming'",
		llm=llm,
		browser_context=context,
		controller=controller,
	)

	history: AgentHistoryList = await agent.run(max_steps=2)

	# Verify that only open_tab was used
	action_names = history.action_names()

	# Only open_tab should be in the actions
	assert all(action == 'open_tab' for action in action_names), (
		f'Found unexpected actions: {[a for a in action_names if a != "open_tab"]}'
	)

	# open_tab should be used at least once
	assert 'open_tab' in action_names, 'open_tab action was not used'
