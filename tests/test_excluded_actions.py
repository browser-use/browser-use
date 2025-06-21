import pytest

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList
from browser_use.browser import BrowserSession
from browser_use.controller.service import Controller

# run with:
# python -m pytest tests/test_excluded_actions.py -v -k "test_only_open_tab_allowed" --capture=no


class MockLLM:
	"""Mock LLM for testing"""

	async def ainvoke(self, prompt):
		class MockResponse:
			content = 'Mocked LLM response'

		return MockResponse()


@pytest.fixture(scope='module')
async def browser_session():
	browser_session = BrowserSession(
		headless=True,
		user_data_dir=None,
	)
	await browser_session.start()
	yield browser_session
	await browser_session.stop()


@pytest.fixture
def llm():
	"""Initialize language model for testing"""
	return MockLLM()


# pytest tests/test_excluded_actions.py -v -k "test_only_open_tab_allowed" --capture=no
async def test_only_open_tab_allowed(llm, browser_session):
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
		browser_session=browser_session,
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
