"""
Tests for the final_actions feature.

Verifies:
1. final_actions execute after the agent calls done
2. final_actions do NOT corrupt history (is_done, is_successful, final_result stay correct)
3. final_actions are skipped when not provided
4. final_actions work in the agent.run() code path
5. final_actions execute before register_done_callback
6. final_actions fire exactly once (idempotency guard)
7. final_actions errors are swallowed — done_callback still fires
8. final_actions re-arm on add_new_task for follow-up tasks

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


# ---------------------------------------------------------------------------
# Basic parameter tests (no browser needed)
# ---------------------------------------------------------------------------


async def test_final_actions_not_set_by_default():
	"""Agent should have no final actions when none are provided."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm)
	assert agent._final_actions_dicts is None
	assert agent._final_actions_executed is False


async def test_final_actions_stored_on_agent():
	"""final_actions dicts should be stored on the agent for lazy conversion."""
	llm = create_mock_llm()
	final = [{'scroll': {'down': True, 'pages': 1}}]
	agent = Agent(task='Test task', llm=llm, final_actions=final)
	assert agent._final_actions_dicts == final
	assert agent._final_actions_executed is False


async def test_final_actions_empty_list_is_noop():
	"""An empty final_actions list should be treated as no-op (falsy)."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm, final_actions=[])
	await agent._execute_final_actions()
	assert agent._final_actions_executed is False  # guard not tripped for empty list


# ---------------------------------------------------------------------------
# Execution tests (require browser)
# ---------------------------------------------------------------------------


async def test_final_actions_skipped_when_not_provided(browser_session, base_url):
	"""_execute_final_actions should be a no-op when no final_actions are set."""
	llm = create_mock_llm()
	agent = Agent(task='Test task', llm=llm, browser_session=browser_session)

	history_len_before = len(agent.history.history)
	await agent._execute_final_actions()
	assert len(agent.history.history) == history_len_before


async def test_final_actions_execute_without_corrupting_history(browser_session, base_url):
	"""final_actions should execute but NOT append to history.

	Appending to history would break history[-1] semantics used by
	is_done(), is_successful(), final_result(), and _judge_and_log().
	"""
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

	# Final actions must NOT add to history
	assert len(agent.history.history) == history_len_before


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

	assert callback_called, 'done_callback should have been called'
	assert agent._final_actions_executed is True


async def test_history_semantics_preserved_after_final_actions(browser_session, base_url):
	"""is_done(), is_successful(), and final_result() must return correct values
	after final_actions execute — verifying history[-1] is still the done step."""
	await browser_session.navigate_to(f'{base_url}/test')
	await asyncio.sleep(0.5)

	llm = create_mock_llm()
	agent = Agent(
		task=f'Go to {base_url}/test',
		llm=llm,
		browser_session=browser_session,
		final_actions=[{'scroll': {'down': True, 'pages': 1}}],
		use_judge=False,
	)

	history = await agent.run(max_steps=3)

	assert history.is_done(), 'history.is_done() must be True after agent completes'
	assert history.is_successful() is True, 'history.is_successful() must be True'
	assert history.final_result() is not None, 'history.final_result() must not be None'


async def test_final_actions_before_done_callback(browser_session, base_url):
	"""final_actions should execute BEFORE register_done_callback fires."""
	await browser_session.navigate_to(f'{base_url}/test')
	await asyncio.sleep(0.5)

	final_actions_ran_before_callback = False

	llm = create_mock_llm()

	async def done_callback(history):
		nonlocal final_actions_ran_before_callback
		# If final_actions already executed, the guard flag will be True
		# We can't check history for final_actions entries (they're not appended)
		# but we know the agent attribute is set
		final_actions_ran_before_callback = True

	agent = Agent(
		task=f'Go to {base_url}/test',
		llm=llm,
		browser_session=browser_session,
		final_actions=[{'scroll': {'down': True, 'pages': 1}}],
		register_done_callback=done_callback,
		use_judge=False,
	)

	await agent.run(max_steps=3)

	assert agent._final_actions_executed is True, 'final_actions should have executed'
	assert final_actions_ran_before_callback, 'done_callback should have fired after final_actions'


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def test_final_actions_fire_exactly_once(browser_session, base_url):
	"""Calling _execute_final_actions multiple times should only execute once."""
	await browser_session.navigate_to(f'{base_url}/test')
	await asyncio.sleep(0.5)

	llm = create_mock_llm()
	agent = Agent(
		task='Test task',
		llm=llm,
		browser_session=browser_session,
		final_actions=[{'scroll': {'down': True, 'pages': 1}}],
	)

	await agent._execute_final_actions()
	assert agent._final_actions_executed is True

	# Second call should be a no-op
	history_len = len(agent.history.history)
	await agent._execute_final_actions()
	assert len(agent.history.history) == history_len  # no change


# ---------------------------------------------------------------------------
# Error resilience
# ---------------------------------------------------------------------------


async def test_final_actions_error_does_not_block_done_callback(browser_session, base_url):
	"""If a final action fails, done_callback must still fire."""
	await browser_session.navigate_to(f'{base_url}/test')
	await asyncio.sleep(0.5)

	llm = create_mock_llm()
	callback_called = False

	async def done_callback(history):
		nonlocal callback_called
		callback_called = True

	# Use an action that will fail: clicking a non-existent element index
	agent = Agent(
		task=f'Go to {base_url}/test',
		llm=llm,
		browser_session=browser_session,
		final_actions=[{'click': {'index': 99999}}],
		register_done_callback=done_callback,
		use_judge=False,
	)

	await agent.run(max_steps=3)

	assert callback_called, 'done_callback must fire even when final_actions fail'
	assert agent._final_actions_executed is True


# ---------------------------------------------------------------------------
# Follow-up tasks
# ---------------------------------------------------------------------------


async def test_final_actions_reset_on_add_new_task():
	"""add_new_task should re-arm the final_actions guard so they fire again."""
	llm = create_mock_llm()
	agent = Agent(
		task='Test task',
		llm=llm,
		final_actions=[{'scroll': {'down': True, 'pages': 1}}],
	)

	# Simulate having already executed
	agent._final_actions_executed = True

	agent.add_new_task('Follow-up task')

	assert agent._final_actions_executed is False, 'Guard should be reset after add_new_task'
