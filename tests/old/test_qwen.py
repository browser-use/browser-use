import pytest
from langchain_ollama import ChatOllama

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList
from browser_use.browser import BrowserProfile, BrowserSession


@pytest.fixture
def llm():
	"""Initialize language model for testing"""

	# return ChatAnthropic(model_name='claude-3-5-sonnet-20240620', timeout=25, stop=None)
	# NOTE: Make sure to run ollama server with `ollama start'
	return ChatOllama(
		model='qwen2.5:latest',
		num_ctx=128000,
	)


@pytest.fixture
async def browser_session():
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.stop()


# pytest tests/test_qwen.py -v -k "test_qwen_url" --capture=no
async def test_qwen_url(llm, browser_session):
	"""Test complex ecommerce interaction sequence"""
	agent = Agent(
		task='go_to_url amazon.com',
		llm=llm,
		browser_session=browser_session,
	)

	history: AgentHistoryList = await agent.run(max_steps=3)

	# Verify sequence of actions
	action_sequence = []
	for action in history.model_actions():
		action_name = list(action.keys())[0]
		if action_name in ['go_to_url', 'open_tab']:
			action_sequence.append('navigate')

	assert 'navigate' in action_sequence  # Navigated to Amazon
