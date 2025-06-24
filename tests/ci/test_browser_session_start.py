"""
Test script for BrowserSession.start() method to ensure proper initialization,
concurrency handling, and error handling.

Tests cover:
- Calling .start() on a session that's already started
- Simultaneously calling .start() from two parallel coroutines
- Calling .start() on a session that's started but has a closed browser connection
- Calling .close() on a session that hasn't been started yet
"""

import asyncio
import json
import logging
import tempfile
from pathlib import Path

import pytest

from browser_use.browser.profile import (
	BROWSERUSE_DEFAULT_CHANNEL,
	BrowserChannel,
	BrowserProfile,
)
from browser_use.browser.session import BrowserSession
from browser_use.config import CONFIG
from tests.ci.conftest import create_mock_llm

# Set up test logging
logger = logging.getLogger('browser_session_start_tests')
# logger.setLevel(logging.DEBUG)


class TestBrowserSessionStart:
	"""Tests for BrowserSession.start() method initialization and concurrency."""

	@pytest.fixture(scope='module')
	async def browser_profile(self):
		"""Create and provide a BrowserProfile with headless mode."""
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		yield profile

	@pytest.fixture(scope='function')
	async def browser_session(self, browser_profile):
		"""Create a BrowserSession instance without starting it."""
		session = BrowserSession(browser_profile=browser_profile)
		yield session
		await session.kill()

	async def test_start_already_started_session(self, browser_session):
		"""Test calling .start() on a session that's already started."""
		# logger.info('Testing start on already started session')

		# Start the session for the first time
		result1 = await browser_session.start()
		assert browser_session.initialized is True
		assert browser_session.browser_context is not None
		assert result1 is browser_session

		# Start the session again - should return immediately without re-initialization
		result2 = await browser_session.start()
		assert result2 is browser_session
		assert browser_session.initialized is True
		assert browser_session.browser_context is not None

		# Both results should be the same instance
		assert result1 is result2

	async def test_concurrent_start_calls(self, browser_session):
		"""Test simultaneously calling .start() from two parallel coroutines."""
		# logger.info('Testing concurrent start calls')

		# Track how many times the lock is actually acquired for initialization
		original_start_lock = browser_session._start_lock
		lock_acquire_count = 0

		class CountingLock:
			def __init__(self, original_lock):
				self.original_lock = original_lock

			async def __aenter__(self):
				nonlocal lock_acquire_count
				lock_acquire_count += 1
				return await self.original_lock.__aenter__()

			async def __aexit__(self, exc_type, exc_val, exc_tb):
				return await self.original_lock.__aexit__(exc_type, exc_val, exc_tb)

		browser_session._start_lock = CountingLock(original_start_lock)

		# Start two concurrent calls to start()
		results = await asyncio.gather(browser_session.start(), browser_session.start(), return_exceptions=True)

		# Both should succeed and return the same session instance
		assert all(result is browser_session for result in results)
		assert browser_session.initialized is True
		assert browser_session.browser_context is not None

		# The lock should have been acquired twice (once per coroutine)
		# but only one should have done the actual initialization
		assert lock_acquire_count == 2

	async def test_start_with_closed_browser_connection(self, browser_session):
		"""Test calling .start() on a session that's started but has a closed browser connection."""
		# logger.info('Testing start with closed browser connection')

		# Start the session normally
		await browser_session.start()
		assert browser_session.initialized is True
		assert browser_session.browser_context is not None

		# Simulate a closed browser connection by closing the browser
		if browser_session.browser:
			await browser_session.browser.close()

		# The session should detect the closed connection and reinitialize
		result = await browser_session.start()
		assert result is browser_session
		assert browser_session.initialized is True
		assert browser_session.browser_context is not None

	async def test_start_with_missing_browser_context(self, browser_session):
		"""Test calling .start() when browser_context is None but initialized is True."""
		# logger.info('Testing start with missing browser context')

		# Manually set initialized to True but leave browser_context as None
		browser_session.initialized = True
		browser_session.browser_context = None

		# Start should detect this inconsistent state and reinitialize
		result = await browser_session.start()
		assert result is browser_session
		assert browser_session.initialized is True
		assert browser_session.browser_context is not None

	async def test_start_initialization_failure(self, browser_session):
		"""Test that initialization failure properly resets the initialized flag."""
		# logger.info('Testing start initialization failure')

		# Mock setup_playwright to raise an exception
		original_setup_playwright = browser_session.setup_playwright

		async def failing_setup_playwright():
			raise RuntimeError('Simulated initialization failure')

		browser_session.setup_playwright = failing_setup_playwright

		# Start should fail and reset initialized flag
		with pytest.raises(RuntimeError, match='Simulated initialization failure'):
			await browser_session.start()

		assert browser_session.initialized is False

		# Restore the original method and try again - should work
		browser_session.setup_playwright = original_setup_playwright
		result = await browser_session.start()
		assert result is browser_session
		assert browser_session.initialized is True

	async def test_close_unstarted_session(self, browser_session):
		"""Test calling .close() on a session that hasn't been started yet."""
		# logger.info('Testing close on unstarted session')

		# Ensure session is not started
		assert browser_session.initialized is False
		assert browser_session.browser_context is None

		# Close should not raise an exception
		await browser_session.stop()

		# State should remain unchanged
		assert browser_session.initialized is False
		assert browser_session.browser_context is None

	async def test_close_alias_method(self, browser_session):
		"""Test the deprecated .close() alias method."""
		# logger.info('Testing deprecated close alias method')

		# Start the session
		await browser_session.start()
		assert browser_session.initialized is True

		# Use the deprecated close method
		await browser_session.close()

		# Session should be stopped
		assert browser_session.initialized is False

	async def test_context_manager_usage(self, browser_session):
		"""Test using BrowserSession as an async context manager."""
		# logger.info('Testing context manager usage')

		# Use as context manager
		async with browser_session as session:
			assert session is browser_session
			assert session.initialized is True
			assert session.browser_context is not None

		# Should be stopped after exiting context
		assert browser_session.initialized is False

	async def test_multiple_concurrent_operations_after_start(self, browser_session):
		"""Test that multiple operations can run concurrently after start() completes."""
		# logger.info('Testing multiple concurrent operations after start')

		# Start the session
		await browser_session.start()

		# Run multiple operations concurrently that require initialization
		async def get_tabs():
			return await browser_session.get_tabs_info()

		async def get_current_page():
			return await browser_session.get_current_page()

		async def take_screenshot():
			return await browser_session.take_screenshot()

		# All operations should succeed concurrently
		results = await asyncio.gather(get_tabs(), get_current_page(), take_screenshot(), return_exceptions=True)

		# Check that all operations completed successfully
		assert len(results) == 3
		assert all(not isinstance(r, Exception) for r in results)

	async def test_require_initialization_decorator_already_started(self, browser_session):
		"""Test @require_initialization decorator when session is already started."""
		# logger.info('Testing @require_initialization decorator with already started session')

		# Start the session first
		await browser_session.start()
		assert browser_session.initialized is True
		assert browser_session.browser_context is not None

		# Track if start() gets called again by monitoring the lock acquisition
		original_start_lock = browser_session._start_lock
		lock_acquire_count = 0

		class CountingLock:
			def __init__(self, original_lock):
				self._original_lock = original_lock

			async def __aenter__(self):
				nonlocal lock_acquire_count
				lock_acquire_count += 1
				return await self._original_lock.__aenter__()

			async def __aexit__(self, exc_type, exc_val, exc_tb):
				return await self._original_lock.__aexit__(exc_type, exc_val, exc_tb)

		browser_session._start_lock = CountingLock(original_start_lock)

		# Call a method decorated with @require_initialization
		# This should work without calling start() again
		tabs_info = await browser_session.get_tabs_info()

		# Verify the method worked and start() wasn't called again (lock not acquired)
		assert isinstance(tabs_info, list)
		assert lock_acquire_count == 0  # start() should not have been called
		assert browser_session.initialized is True

	async def test_require_initialization_decorator_not_started(self, browser_session):
		"""Test @require_initialization decorator when session is not started."""
		# logger.info('Testing @require_initialization decorator with unstarted session')

		# Ensure session is not started
		assert browser_session.initialized is False
		assert browser_session.browser_context is None

		# Track calls to start() method
		original_start = browser_session.start
		start_call_count = 0

		async def counting_start():
			nonlocal start_call_count
			start_call_count += 1
			return await original_start()

		browser_session.start = counting_start

		# Call a method that requires initialization
		tabs_info = await browser_session.get_tabs_info()

		# Verify the decorator called start() and the session is now initialized
		assert start_call_count == 1  # start() should have been called once
		assert browser_session.initialized is True
		assert browser_session.browser_context is not None
		assert isinstance(tabs_info, list)  # Should return valid tabs info

	async def test_require_initialization_decorator_with_closed_page(self, browser_session):
		"""Test @require_initialization decorator handles closed pages correctly."""
		# logger.info('Testing @require_initialization decorator with closed page')

		# Start the session and get a page
		await browser_session.start()
		current_page = await browser_session.get_current_page()
		assert current_page is not None
		assert not current_page.is_closed()

		# Close the current page
		await current_page.close()

		# Call a method decorated with @require_initialization
		# This should create a new tab since the current page is closed
		tabs_info = await browser_session.get_tabs_info()

		# Verify a new page was created
		assert isinstance(tabs_info, list)
		new_current_page = await browser_session.get_current_page()
		assert new_current_page is not None
		assert not new_current_page.is_closed()
		assert new_current_page != current_page  # Should be a different page

	async def test_concurrent_stop_calls(self, browser_profile):
		"""Test simultaneous calls to stop() from multiple coroutines."""
		# logger.info('Testing concurrent stop calls')

		# Create a single session for this test
		browser_session = BrowserSession(browser_profile=browser_profile)
		await browser_session.start()
		assert browser_session.initialized is True
		assert browser_session.browser_context is not None

		# Create a lock to ensure only one stop actually executes
		stop_lock = asyncio.Lock()
		stop_execution_count = 0

		async def safe_stop():
			nonlocal stop_execution_count
			async with stop_lock:
				if browser_session.initialized:
					stop_execution_count += 1
					await browser_session.stop()
			return 'stopped'

		# Call stop() concurrently from multiple coroutines
		results = await asyncio.gather(safe_stop(), safe_stop(), safe_stop(), return_exceptions=True)

		# All calls should succeed without errors
		assert all(not isinstance(r, Exception) for r in results)

		# Only one stop should have actually executed
		assert stop_execution_count == 1

		# Session should be stopped
		assert browser_session.initialized is False
		assert browser_session.browser_context is None

	async def test_stop_with_closed_browser_context(self, browser_session):
		"""Test calling stop() when browser context is already closed."""
		# logger.info('Testing stop with closed browser context')

		# Start the session
		await browser_session.start()
		assert browser_session.initialized is True
		browser_ctx = browser_session.browser_context
		assert browser_ctx is not None

		# Manually close the browser context
		await browser_ctx.close()

		# stop() should handle this gracefully
		await browser_session.stop()

		# Session should be properly cleaned up
		assert browser_session.initialized is False
		assert browser_session.browser_context is None

	async def test_access_after_stop(self, browser_profile):
		"""Test accessing browser context after stop() to ensure proper cleanup."""
		# logger.info('Testing access after stop')

		# Create a session without fixture to avoid double cleanup
		browser_session = BrowserSession(browser_profile=browser_profile)

		# Start and stop the session
		await browser_session.start()
		await browser_session.stop()

		# Verify session is stopped
		assert browser_session.initialized is False
		assert browser_session.browser_context is None

		# calling a method wrapped in @require_initialization should auto-restart the session
		await browser_session.get_tabs_info()
		assert browser_session.initialized is True

	async def test_race_condition_between_stop_and_operation(self, browser_session):
		"""Test race condition between stop() and other operations."""
		# logger.info('Testing race condition between stop and operations')

		await browser_session.start()

		# Create a barrier to synchronize the operations
		barrier = asyncio.Barrier(2)

		async def stop_session():
			await barrier.wait()  # Wait for both coroutines to be ready
			await browser_session.stop()
			return 'stopped'

		async def perform_operation():
			await barrier.wait()  # Wait for both coroutines to be ready
			try:
				# This might fail if stop() executes first
				return await browser_session.get_tabs_info()
			except Exception as e:
				return f'error: {type(e).__name__}'

		# Run both operations concurrently
		results = await asyncio.gather(stop_session(), perform_operation(), return_exceptions=True)

		# One should succeed, the other might fail or succeed depending on timing
		assert 'stopped' in results
		# The operation might succeed (returning a list) or fail gracefully
		other_result = results[1] if results[0] == 'stopped' else results[0]
		assert isinstance(other_result, (list, str))

	async def test_multiple_start_stop_cycles(self, browser_session):
		"""Test multiple start/stop cycles to ensure no resource leaks."""
		# logger.info('Testing multiple start/stop cycles')

		# Perform multiple start/stop cycles
		for i in range(3):
			# Start
			await browser_session.start()
			assert browser_session.initialized is True
			assert browser_session.browser_context is not None

			# Perform an operation
			tabs = await browser_session.get_tabs_info()
			assert isinstance(tabs, list)

			# Stop
			await browser_session.stop()
			assert browser_session.initialized is False
			assert browser_session.browser_context is None

	async def test_context_manager_with_exception(self, browser_session):
		"""Test context manager properly closes even when exception occurs."""
		# logger.info('Testing context manager with exception')

		class TestException(Exception):
			pass

		# Use context manager and raise exception inside
		with pytest.raises(TestException):
			async with browser_session as session:
				assert session.initialized is True
				assert session.browser_context is not None
				raise TestException('Test exception')

		# Session should still be stopped despite the exception
		assert browser_session.initialized is False
		assert browser_session.browser_context is None

	async def test_session_without_fixture(self):
		"""Test creating a session without using fixture."""
		# Create a new profile and session for this test
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		session = BrowserSession(browser_profile=profile)

		try:
			await session.start()
			assert session.initialized is True
			await session.stop()
			assert session.initialized is False
		finally:
			pass

	async def test_start_with_keep_alive_profile(self):
		"""Test start/stop behavior with keep_alive=True profile."""
		# Create a completely fresh profile and session to avoid module-scoped fixture issues
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		session = BrowserSession(browser_profile=profile)

		try:
			# Start the session
			await session.start()
			assert session.initialized is True

			# Now test keep_alive behavior
			session.browser_profile.keep_alive = True

			# Stop should not actually close the browser with keep_alive=True
			await session.stop()
			# Browser should still be connected
			assert session.initialized is True
			assert session.browser_context and session.browser_context.pages[0]

		finally:
			await session.kill()

	async def test_user_data_dir_not_allowed_to_corrupt_default_profile(self, caplog):
		"""Test user_data_dir handling for different browser channels and version mismatches."""
		import logging

		# Temporarily enable propagation for browser_use logger to capture logs
		browser_use_logger = logging.getLogger('browser_use')
		original_propagate = browser_use_logger.propagate
		browser_use_logger.propagate = True

		caplog.set_level(logging.WARNING, logger='browser_use.utils')

		# Test 1: Chromium with default user_data_dir and default channel should work fine
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR,
				channel=BROWSERUSE_DEFAULT_CHANNEL,  # chromium
				keep_alive=False,
			),
		)

		try:
			await session.start()
			assert session.initialized is True
			assert session.browser_context is not None
			# Verify the user_data_dir wasn't changed
			assert session.browser_profile.user_data_dir == CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR
		finally:
			await session.kill()

		# Test 2: Chrome with default user_data_dir should show warning and change dir
		profile2 = BrowserProfile(
			headless=True,
			user_data_dir=CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR,
			channel=BrowserChannel.CHROME,
			keep_alive=False,
		)

		# The validator should have changed the user_data_dir
		assert profile2.user_data_dir != CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR
		assert profile2.user_data_dir == CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR.parent / 'default-chrome'

		# Check warning was logged
		warning_found = any(
			'Changing user_data_dir=' in record.message and 'CHROME' in record.message for record in caplog.records
		)
		assert warning_found, 'Expected warning about changing user_data_dir was not found'

		# Restore original propagate setting
		browser_use_logger.propagate = original_propagate

	# only run if `/Applications/Brave Browser.app` is installed
	@pytest.mark.skipif(
		not Path('~/.config/browseruse/profiles/stealth').expanduser().exists(), reason='Brave Browser not installed'
	)
	async def test_corrupted_user_data_dir_triggers_warning(self, caplog):
		# # create profile dir with brave
		# brave_profile_dir = Path(tempfile.mkdtemp()) / 'brave'

		# brave_session = BrowserSession(
		# 	executable_path='/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
		# 	headless=True,
		# 	user_data_dir=brave_profile_dir,  # profile created by Brave
		# )
		# await brave_session.start()
		# await brave_session.stop()

		chromium_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir='~/.config/browseruse/profiles/stealth',
				channel=BrowserChannel.CHROMIUM,  # should crash when opened with chromium
			),
		)

		# open chrome with corrupted user_data_dir
		with pytest.raises(Exception, match='Failed parsing extensions'):
			await chromium_session.start()


class TestBrowserSessionReusePatterns:
	"""Tests for all browser re-use patterns documented in docs/customize/real-browser.mdx"""

	async def test_sequential_agents_same_profile_different_browser(self, mock_llm):
		"""Test Sequential Agents, Same Profile, Different Browser pattern"""
		from browser_use import Agent
		from browser_use.browser.profile import BrowserProfile

		# Create a reusable profile
		reused_profile = BrowserProfile(
			user_data_dir=None,  # Use temp dir for testing
			headless=True,
		)

		# First agent
		agent1 = Agent(
			task='The first task...',
			llm=mock_llm,
			browser_profile=reused_profile,
			tool_calling_method='raw',  # Use raw mode for tests
			enable_memory=False,  # Disable memory for tests
		)
		await agent1.run()

		# Verify first agent's session is closed
		assert agent1.browser_session is not None
		assert not agent1.browser_session.initialized

		# Second agent with same profile
		agent2 = Agent(
			task='The second task...',
			llm=mock_llm,
			browser_profile=reused_profile,
			tool_calling_method='raw',  # Use raw mode for tests
			enable_memory=False,  # Disable memory for tests
		)
		await agent2.run()

		# Verify second agent created a new session
		assert agent2.browser_session is not None
		assert agent1.browser_session is not agent2.browser_session
		assert not agent2.browser_session.initialized

	async def test_sequential_agents_same_profile_same_browser(self, mock_llm):
		"""Test Sequential Agents, Same Profile, Same Browser pattern"""
		from browser_use import Agent, BrowserSession

		# Create a reusable session with keep_alive
		reused_session = BrowserSession(
			browser_profile=BrowserProfile(
				user_data_dir=None,  # Use temp dir for testing
				headless=True,
				keep_alive=True,  # Don't close browser after agent.run()
			),
		)

		try:
			# Start the session manually (agents will reuse this initialized session)
			await reused_session.start()

			# First agent
			agent1 = Agent(
				task='The first task...',
				llm=mock_llm,
				browser_session=reused_session,
				tool_calling_method='raw',  # Use raw mode for tests
				enable_memory=False,  # Disable memory for tests
			)
			await agent1.run()

			# Verify session is still alive
			assert reused_session.initialized
			assert reused_session.browser_context is not None

			# Second agent reusing the same session
			agent2 = Agent(
				task='The second task...',
				llm=mock_llm,
				browser_session=reused_session,
				tool_calling_method='raw',  # Use raw mode for tests
				enable_memory=False,  # Disable memory for tests
			)
			await agent2.run()

			# Verify same browser was used (using __eq__ to check browser_pid, cdp_url, wss_url)
			assert agent1.browser_session == agent2.browser_session
			assert agent1.browser_session == reused_session
			assert reused_session.initialized

		finally:
			await reused_session.kill()

	async def test_parallel_agents_same_browser_multiple_tabs(self, httpserver):
		"""Test Parallel Agents, Same Browser, Multiple Tabs pattern"""

		from browser_use import Agent, BrowserSession

		# Create a shared browser session
		with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as f:
			# Write minimal valid storage state
			f.write('{"cookies": [], "origins": []}')
			storage_state_path = f.name

		# Convert to Path object to fix storage state type error
		from pathlib import Path

		storage_state_path = Path(storage_state_path)

		shared_browser = BrowserSession(
			browser_profile=BrowserProfile(
				storage_state=storage_state_path,
				user_data_dir=None,
				keep_alive=True,
				headless=True,
			),
		)

		try:
			# Set up httpserver
			httpserver.expect_request('/').respond_with_data('<html><body>Test page</body></html>')
			test_url = httpserver.url_for('/')

			# Start the session before passing it to agents
			await shared_browser.start()

			# Create action sequences for each agent
			# Each agent creates a new tab then completes
			tab_creation_action = (
				"""
			{
				"thinking": "null",
				"evaluation_previous_goal": "Starting the task",
				"memory": "Need to create a new tab",
				"next_goal": "Create a new tab to work in",
				"action": [
					{
						"open_tab": {
							"url": "%s"
						}
					}
				]
			}
			"""
				% test_url
			)

			done_action = """
			{
				"thinking": "null",
				"evaluation_previous_goal": "Tab created",
				"memory": "Task completed in new tab",
				"next_goal": "Complete the task",
				"action": [
					{
						"done": {
							"text": "Task completed successfully",
							"success": true
						}
					}
				]
			}
			"""

			# Create 3 agents sharing the same browser session
			# Each gets its own mock LLM with the same action sequence
			mock_llm1 = create_mock_llm([tab_creation_action, done_action])
			mock_llm2 = create_mock_llm([tab_creation_action, done_action])
			mock_llm3 = create_mock_llm([tab_creation_action, done_action])

			agent1 = Agent(
				task='First parallel task...',
				llm=mock_llm1,
				browser_session=shared_browser,
				tool_calling_method='raw',  # Use raw mode for tests
				enable_memory=False,  # Disable memory for tests
			)
			agent2 = Agent(
				task='Second parallel task...',
				llm=mock_llm2,
				browser_session=shared_browser,
				tool_calling_method='raw',  # Use raw mode for tests
				enable_memory=False,  # Disable memory for tests
			)
			agent3 = Agent(
				task='Third parallel task...',
				llm=mock_llm3,
				browser_session=shared_browser,
				tool_calling_method='raw',  # Use raw mode for tests
				enable_memory=False,  # Disable memory for tests
			)

			# Run all agents in parallel
			_results = await asyncio.gather(agent1.run(), agent2.run(), agent3.run())

			# Verify all agents used the same browser session (using __eq__ to check browser_pid, cdp_url, wss_url)
			# Debug: print the browser sessions to see what's different
			print(f'Agent1 session: {agent1.browser_session}')
			print(f'Agent2 session: {agent2.browser_session}')
			print(f'Agent3 session: {agent3.browser_session}')
			print(f'Shared session: {shared_browser}')

			# Check each pair individually
			assert agent1.browser_session == agent2.browser_session, (
				f'agent1 != agent2: {agent1.browser_session} != {agent2.browser_session}'
			)
			assert agent2.browser_session == agent3.browser_session, (
				f'agent2 != agent3: {agent2.browser_session} != {agent3.browser_session}'
			)
			assert agent1.browser_session == shared_browser, f'agent1 != shared: {agent1.browser_session} != {shared_browser}'
			assert shared_browser.initialized

			# Verify multiple tabs were created
			tabs_info = await shared_browser.get_tabs_info()
			# Should have at least 3 tabs (one per agent)
			assert len(tabs_info) >= 3

		finally:
			await shared_browser.kill()
			storage_state_path.unlink(missing_ok=True)

	async def test_parallel_agents_same_browser_same_tab(self, mock_llm, httpserver):
		"""Test Parallel Agents, Same Browser, Same Tab pattern (not recommended)"""
		from browser_use import Agent, BrowserSession

		# Create a browser session and start it first
		shared_browser = BrowserSession(
			browser_profile=BrowserProfile(
				user_data_dir=None,
				headless=True,
				keep_alive=True,  # Keep the browser alive for reuse
			),
		)

		try:
			await shared_browser.start()

			# Create agents sharing the same browser session
			# They will share the same tab since we're not creating new tabs
			agent1 = Agent(
				task='Fill out the form in section A...',
				llm=mock_llm,
				browser_session=shared_browser,
				tool_calling_method='raw',  # Use raw mode for tests
				enable_memory=False,  # Disable memory for tests
			)
			agent2 = Agent(
				task='Fill out the form in section B...',
				llm=mock_llm,
				browser_session=shared_browser,
				tool_calling_method='raw',  # Use raw mode for tests
				enable_memory=False,  # Disable memory for tests
			)

			# Set up httpserver and navigate to a page before running agents
			httpserver.expect_request('/').respond_with_data('<html><body>Test page</body></html>')
			page = await shared_browser.get_current_page()
			await page.goto(httpserver.url_for('/'), wait_until='domcontentloaded')

			# Run agents in parallel (may interfere with each other)
			_results = await asyncio.gather(agent1.run(), agent2.run(), return_exceptions=True)

			# Verify both agents used the same browser session
			assert agent1.browser_session == agent2.browser_session
			assert agent1.browser_session == shared_browser

		finally:
			# Clean up
			await shared_browser.kill()

	async def test_parallel_agents_same_profile_different_browsers(self, mock_llm):
		"""Test Parallel Agents, Same Profile, Different Browsers pattern (recommended)"""

		from browser_use import Agent
		from browser_use.browser import BrowserProfile, BrowserSession

		# Create a shared profile with storage state
		with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as f:
			# Write minimal valid storage state
			f.write('{"cookies": [], "origins": [{"origin": "https://example.com", "localStorage": []}]}')
			auth_json_path = f.name

		# Convert to Path object
		from pathlib import Path

		auth_json_path = Path(auth_json_path)

		shared_profile = BrowserProfile(
			headless=True,
			user_data_dir=None,  # Use dedicated tmp user_data_dir per session
			storage_state=auth_json_path,  # Load/save cookies to/from json file
			keep_alive=True,
		)

		try:
			# Create separate browser sessions from the same profile
			window1 = BrowserSession(browser_profile=shared_profile)
			await window1.start()
			agent1 = Agent(
				task='First agent task...', llm=mock_llm, browser_session=window1, tool_calling_method='raw', enable_memory=False
			)

			window2 = BrowserSession(browser_profile=shared_profile)
			await window2.start()
			agent2 = Agent(
				task='Second agent task...', llm=mock_llm, browser_session=window2, tool_calling_method='raw', enable_memory=False
			)

			# Run agents in parallel
			_results = await asyncio.gather(agent1.run(), agent2.run())

			# Verify different browser sessions were used
			assert agent1.browser_session is not agent2.browser_session
			assert window1 is not window2

			# Both sessions should be initialized
			assert window1.initialized
			assert window2.initialized

			# Save storage state from both sessions
			await window1.save_storage_state()
			await window2.save_storage_state()

			# Verify storage state file exists
			assert Path(auth_json_path).exists()

			# Verify storage state file was not wiped
			storage_state = json.loads(auth_json_path.read_text())
			assert 'origins' in storage_state
			assert len(storage_state['origins']) > 0

		finally:
			await window1.kill()
			await window2.kill()
			auth_json_path.unlink(missing_ok=True)

	async def test_browser_shutdown_isolated(self):
		"""Test that browser shutdown doesnt affect other browser_sessions"""
		from browser_use import BrowserSession

		browser_session1 = BrowserSession(
			browser_profile=BrowserProfile(
				user_data_dir=None,
				headless=True,
				keep_alive=True,  # Keep the browser alive for reuse
			),
		)
		browser_session2 = BrowserSession(
			browser_profile=BrowserProfile(
				user_data_dir=None,
				headless=True,
				keep_alive=True,  # Keep the browser alive for reuse
			),
		)
		await browser_session1.start()
		await browser_session2.start()

		assert await browser_session1.is_connected()
		assert await browser_session2.is_connected()
		assert browser_session1.browser_context != browser_session2.browser_context

		await browser_session1.create_new_tab('chrome://version')
		await browser_session2.create_new_tab('chrome://settings')

		await browser_session2.kill()

		# ensure that the browser_session1 is still connected and unaffected by the kill of browser_session2
		assert await browser_session1.is_connected()
		assert browser_session1.browser_context is not None
		await browser_session1.create_new_tab('chrome://settings')
		await browser_session1.browser_context.pages[0].evaluate('alert(1)')

		await browser_session1.kill()

	async def test_many_parallel_browser_sessions(self):
		"""Test spawning 20 parallel browser_sessions with different settings and ensure they all work"""
		from browser_use import BrowserSession

		browser_sessions = []

		for i in range(5):
			browser_sessions.append(
				BrowserSession(
					browser_profile=BrowserProfile(
						user_data_dir=None,
						headless=True,
						keep_alive=True,
					),
				)
			)
		for i in range(5):
			browser_sessions.append(
				BrowserSession(
					browser_profile=BrowserProfile(
						user_data_dir=Path(tempfile.mkdtemp(prefix=f'browseruse-tmp-{i}')),
						headless=True,
						keep_alive=True,
					),
				)
			)
		for i in range(5):
			browser_sessions.append(
				BrowserSession(
					browser_profile=BrowserProfile(
						user_data_dir=None,
						headless=True,
						keep_alive=False,
					),
				)
			)
		for i in range(5):
			browser_sessions.append(
				BrowserSession(
					browser_profile=BrowserProfile(
						user_data_dir=Path(tempfile.mkdtemp(prefix=f'browseruse-tmp-{i}')),
						headless=True,
						keep_alive=False,
					),
				)
			)

		await asyncio.gather(*[browser_session.start() for browser_session in browser_sessions])

		# ensure all are connected and usable
		new_tab_tasks = []
		for browser_session in browser_sessions:
			assert await browser_session.is_connected()
			assert browser_session.browser_context is not None
			new_tab_tasks.append(browser_session.create_new_tab('chrome://version'))
		await asyncio.gather(*new_tab_tasks)

		# kill every 3rd browser_session
		kill_tasks = []
		for i in range(0, len(browser_sessions), 3):
			kill_tasks.append(browser_sessions[i].kill())
			browser_sessions[i] = None
		await asyncio.gather(*kill_tasks)

		# ensure the remaining browser_sessions are still connected and usable
		new_tab_tasks = []
		screenshot_tasks = []
		for browser_session in filter(bool, browser_sessions):
			assert await browser_session.is_connected()
			assert browser_session.browser_context is not None
			new_tab_tasks.append(browser_session.create_new_tab('chrome://version'))
			screenshot_tasks.append(browser_session.take_screenshot())
		await asyncio.gather(*new_tab_tasks)
		await asyncio.gather(*screenshot_tasks)

		kill_tasks = []
		for browser_session in filter(bool, browser_sessions):
			kill_tasks.append(browser_session.kill())
		await asyncio.gather(*kill_tasks)
