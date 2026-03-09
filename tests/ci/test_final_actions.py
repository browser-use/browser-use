"""
Tests for the final_actions feature.

Verifies:
1. final_actions execute after the agent calls done
2. final_actions are recorded in history
3. final_actions are skipped when not provided
4. final_actions work in the agent.run() code path
5. final_actions execute before register_done_callback

Usage:
	uv run pytest tests/ci/test_final_actions.py -v -s
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from tests.ci.conftest import create_mock_llm


@pytest.fixture(scope='session')
def http_server():
	"""Test HTTP server with a simple page."""
	server = HTTPServer()
	server.start()

	server.expect_request('/test').respond_with_data(
		"""<html><head><title>Test Page</title></head><body>
		<h1>Test</h1>
		<p>Test page content</p>
		<a href="/other">Link</a>
		</body></html>""",
		content_type='text/html',
	)

	server.expect_request('/other').respond_with_data(
		"""<html><head><title>Other Page</title></head><body>
		<h1>Other</h1>
		<p>Other page content</p>
		</body></html>""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await session.start()
	yield session
	await session.kill()
	await session.event_bus.stop(clear=True, timeout=5)


async def test_final_actions_not_set_by_default():
	"""Agent should have no final actions when none are provided."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)
	assert agent._final_actions_dicts is None


async def test_final_actions_stored_on_agent():
	"""final_actions dicts should be stored on the agent for lazy conversion."""
	llm = create_mock_llm()
	final = [{'scroll': {'down': True, 'pages': 1}}]
	agent = Agent(task='Test task', llm=llm, final_actions=final)
	assert agent._final_actions_dicts == final


async def test_final_actions_skipped_when_not_provided(browser_session, base_url):
	"""_execute_final_actions should be a no-op when no final_actions are set."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm, browser_session=browser_session)

	# Should not raise or add any history items
	history_len_before = len(agent.history.history)
	await agent._execute_final_actions()
	assert len(agent.history.history) == history_len_before


async def test_final_actions_execute_and_record_history(browser_session, base_url):
	"""final_actions should execute and be saved to history."""
	# Navigate to test page first
	await browser_session.navigate_to(f'{base_url}/test')
	await asyncio.sleep(0.5)

	llm = create_mock_llm()
	agent = Agent(
		task='Test task',
		llm=llm,
		browser_session=browser_session,
		final_actions=[{'scroll': {'down': True, 'pages': 1}}],
	)

	history_len_before = len(agent.history.history)
	await agent._execute_final_actions()

	# Should have added one history item
	assert len(agent.history.history) == history_len_before + 1

	# Check the recorded history
	final_history = agent.history.history[-1]
	assert final_history.state.title == 'Final Actions'
	assert final_history.model_output is not None


async def test_final_actions_execute_on_done(browser_session, base_url):
	"""final_actions should fire when agent.run() completes via done action."""
	await browser_session.navigate_to(f'{base_url}/test')
	await asyncio.sleep(0.5)

	llm = create_mock_llm()

	callback_called = False

	async def done_callback(history):
		nonlocal callback_called
		callback_called = True

	agent = Agent(
		task=f'Go to {base_url}/test',
		llm=llm,
		browser_session=browser_session,
		final_actions=[{'scroll': {'down': True, 'pages': 1}}],
		register_done_callback=done_callback,
		use_judge=False,
	)

	await agent.run(max_steps=3)

	# Both final_actions and done_callback should have fired
	assert callback_called, 'done_callback should have been called'

	# History should contain final actions entry
	final_actions_entries = [h for h in agent.history.history if h.state.title == 'Final Actions']
	assert len(final_actions_entries) == 1, 'final_actions should appear exactly once in history'


async def test_final_actions_before_done_callback(browser_session, base_url):
	"""final_actions should execute BEFORE register_done_callback fires."""
	await browser_session.navigate_to(f'{base_url}/test')
	await asyncio.sleep(0.5)

	execution_order: list[str] = []

	llm = create_mock_llm()

	async def done_callback(history):
		# Check if final actions already ran by looking at history
		final_entries = [h for h in history.history if h.state.title == 'Final Actions']
		if final_entries:
			execution_order.append('done_callback_after_final_actions')
		else:
			execution_order.append('done_callback_before_final_actions')

	agent = Agent(
		task=f'Go to {base_url}/test',
		llm=llm,
		browser_session=browser_session,
		final_actions=[{'scroll': {'down': True, 'pages': 1}}],
		register_done_callback=done_callback,
		use_judge=False,
	)

	await agent.run(max_steps=3)

	assert execution_order == ['done_callback_after_final_actions'], (
		f'final_actions should execute before done_callback, got: {execution_order}'
	)


async def test_final_actions_multiple_actions(browser_session, base_url):
	"""Multiple final actions should all execute."""
	await browser_session.navigate_to(f'{base_url}/test')
	await asyncio.sleep(0.5)

	llm = create_mock_llm()
	agent = Agent(
		task='Test task',
		llm=llm,
		browser_session=browser_session,
		final_actions=[
			{'scroll': {'down': True, 'pages': 1}},
			{'scroll': {'down': False, 'pages': 1}},
		],
	)

	await agent._execute_final_actions()

	final_history = agent.history.history[-1]
	# Should have recorded both actions
	assert len(final_history.model_output.action) == 2
	# Results should have entries for both actions
	assert len(final_history.result) == 2
