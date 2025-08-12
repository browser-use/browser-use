"""Test agent shutdown and cleanup."""

import asyncio
import logging
import threading
import time

from browser_use import Agent, BrowserProfile, BrowserSession
from tests.ci.conftest import create_mock_llm

logger = logging.getLogger(__name__)


async def test_agent_exits_within_10s():
	"""Test that agent with done() exits within 10 seconds."""
	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, keep_alive=False))
	await browser_session.start()

	# Create mock LLM that returns done immediately (default behavior)
	mock_llm = create_mock_llm()

	agent = Agent(
		task='Test task',
		llm=mock_llm,
		browser_session=browser_session,
	)

	start_time = time.time()
	result = await agent.run(max_steps=1)
	exit_time = time.time() - start_time

	assert result.is_done(), 'Agent should have completed'
	assert result.is_successful(), 'Agent should have succeeded'
	assert exit_time < 10, f'Agent took {exit_time:.2f}s to exit (should be < 10s)'

	# Verify browser session was cleaned up
	assert browser_session._cdp_client_root is None, 'Browser session should be cleaned up'


async def test_no_leaked_asyncio_tasks():
	"""Test that no asyncio tasks remain after agent shutdown."""
	# Get initial tasks
	initial_tasks = asyncio.all_tasks(asyncio.get_event_loop())
	initial_count = len(initial_tasks)

	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, keep_alive=False))
	await browser_session.start()

	mock_llm = create_mock_llm()

	agent = Agent(
		task='Test task',
		llm=mock_llm,
		browser_session=browser_session,
	)

	await agent.run(max_steps=1)

	# Wait briefly for cleanup
	await asyncio.sleep(1)

	# Get final tasks
	final_tasks = asyncio.all_tasks(asyncio.get_event_loop())
	final_count = len(final_tasks)

	# Allow some tolerance for framework tasks
	assert final_count <= initial_count + 1, f'Too many tasks remain: {final_count} (initial: {initial_count})'


async def test_no_leaked_threads():
	"""Test that no threads remain after agent shutdown."""
	# Get initial threads (excluding main and asyncio)
	initial_threads = [t for t in threading.enumerate() if t.name not in ['MainThread', 'asyncio_0']]
	initial_count = len(initial_threads)

	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, keep_alive=False))
	await browser_session.start()

	mock_llm = create_mock_llm()

	agent = Agent(
		task='Test task',
		llm=mock_llm,
		browser_session=browser_session,
	)

	await agent.run(max_steps=1)

	# Wait briefly for cleanup
	await asyncio.sleep(1)

	# Get final threads
	final_threads = [t for t in threading.enumerate() if t.name not in ['MainThread', 'asyncio_0']]
	final_count = len(final_threads)

	# No new threads should remain
	assert final_count <= initial_count, f'New threads remain: {final_count} (initial: {initial_count})'


async def test_multiple_agents_cleanup():
	"""Test cleanup with multiple agents run sequentially."""
	exit_times = []

	for i in range(3):
		browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, keep_alive=False))
		await browser_session.start()

		mock_llm = create_mock_llm()

		agent = Agent(
			task=f'Test task {i + 1}',
			llm=mock_llm,
			browser_session=browser_session,
		)

		start_time = time.time()
		result = await agent.run(max_steps=1)
		exit_time = time.time() - start_time

		assert result.is_done(), f'Agent {i + 1} should have completed'
		exit_times.append(exit_time)

		# Small delay between agents
		await asyncio.sleep(0.5)

	# All agents should exit quickly
	for i, exit_time in enumerate(exit_times):
		assert exit_time < 10, f'Agent {i + 1} took {exit_time:.2f}s to exit'

	# Check final state
	tasks = asyncio.all_tasks(asyncio.get_event_loop())
	threads = [t for t in threading.enumerate() if t.name not in ['MainThread', 'asyncio_0']]

	# Should be minimal tasks and no extra threads
	assert len(tasks) <= 3, f'Too many tasks remain: {len(tasks)}'
	assert len(threads) == 0, f'Extra threads remain: {len(threads)}'


async def test_browser_session_stop_method():
	"""Test that BrowserSession.stop() clears event buses without killing browser."""
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			keep_alive=True,  # Keep alive so we can test stop()
		)
	)
	await browser_session.start()

	# Verify browser is connected
	assert browser_session._cdp_client_root is not None, 'Browser should be connected'

	# Call stop() - should clear event buses but keep browser alive
	await browser_session.stop()

	# Browser should still be connected (since we didn't kill it)
	# But event bus should be fresh
	assert browser_session.event_bus is not None, 'Should have fresh event bus'

	# Now kill to clean up
	await browser_session.kill()

	# After kill, browser should be disconnected
	assert browser_session._cdp_client_root is None, 'Browser should be disconnected after kill'
