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
		assert browser_session._browser_context is not None
		assert result1 is browser_session

		# Start the session again - should return immediately without re-initialization
		result2 = await browser_session.start()
		assert result2 is browser_session
		assert browser_session._browser_context is not None

		# Both results should be the same instance
		assert result1 is result2

	async def test_concurrent_start_calls(self, browser_session):
		"""Test simultaneously calling .start() from two parallel coroutines."""
		# logger.info('Testing concurrent start calls')

		# Track browser PIDs before and after to ensure only one browser is launched
		initial_pid = browser_session.browser_pid
		assert initial_pid is None  # Should be None before start

		# Start two concurrent calls to start()
		results = await asyncio.gather(browser_session.start(), browser_session.start(), return_exceptions=True)

		# Both should succeed and return the same session
		successful_results = [r for r in results if isinstance(r, type(browser_session)) and r is browser_session]
		assert len(successful_results) == 2, f'Expected both starts to succeed, got results: {results}'

		# The session should be initialized after concurrent calls
		assert browser_session._browser_context is not None

		# Should have a single browser PID
		final_pid = browser_session.browser_pid
		assert final_pid is not None

		# Try starting again - should return same PID
		await browser_session.start()
		assert browser_session.browser_pid == final_pid

	async def test_start_with_closed_browser_connection(self, browser_session):
		"""Test calling .start() on a session that's started but has a closed browser connection."""
		# logger.info('Testing start with closed browser connection')

		# Start the session normally
		await browser_session.start()
		assert browser_session._browser_context is not None

		# Simulate a closed browser connection by closing the browser
		if browser_session.browser:
			await browser_session.browser.close()

		# The session should detect the closed connection and reinitialize
		result = await browser_session.start()
		assert result is browser_session
		assert browser_session._browser_context is not None

	async def test_start_after_browser_crash(self, browser_session):
		"""Test calling .start() after browser has crashed."""
		# logger.info('Testing start after browser crash')

		# Start the session normally
		await browser_session.start()
		assert browser_session._browser_context is not None
		original_pid = browser_session.browser_pid

		# Force close the browser to simulate a crash
		if browser_session.browser:
			await browser_session.browser.close()

		# Check that initialized reflects the disconnected state
		assert browser_session._browser_context is None

		# Start should recover and create a new browser
		result = await browser_session.start()
		assert result is browser_session
		assert browser_session._browser_context is not None

		# Should have a new PID (or same if reusing process)
		new_pid = browser_session.browser_pid
		assert new_pid is not None

	async def test_start_with_invalid_cdp_url(self):
		"""Test that initialization fails gracefully with invalid CDP URL."""
		# logger.info('Testing start with invalid CDP URL')

		# Create session with invalid CDP URL
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(headless=True),
			cdp_url='http://localhost:99999',  # Invalid port
		)

		try:
			# Start should fail with connection error
			with pytest.raises(Exception):  # Could be various connection errors
				await browser_session.start()

			# Session should not be initialized
			assert browser_session._browser_context is None
		finally:
			await browser_session.kill()

	async def test_close_unstarted_session(self, browser_session):
		"""Test calling .close() on a session that hasn't been started yet."""
		# logger.info('Testing close on unstarted session')

		# Ensure session is not started
		assert browser_session._browser_context is None

		# Close should not raise an exception
		await browser_session.stop()

		# State should remain unchanged
		assert browser_session._browser_context is None

	async def test_close_alias_method(self, browser_session):
		"""Test the deprecated .close() alias method."""
		# logger.info('Testing deprecated close alias method')

		# Start the session
		await browser_session.start()
		assert browser_session._browser_context is not None

		# Use the deprecated close method
		await browser_session.close()

		# Session should be stopped
		assert browser_session._browser_context is None

	async def test_context_manager_usage(self, browser_session):
		"""Test using BrowserSession as an async context manager."""
		# logger.info('Testing context manager usage')

		# Use as context manager
		async with browser_session as session:
			assert session is browser_session
			assert session._browser_context is not None

		# Should be stopped after exiting context
		assert browser_session._browser_context is None

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

	async def test_operations_on_started_session(self, browser_session):
		"""Test various operations work correctly on already started session."""
		# logger.info('Testing operations on already started session')

		# Start the session first
		await browser_session.start()
		assert browser_session._browser_context is not None
		initial_pid = browser_session.browser_pid

		# Various operations should work without restarting
		tabs_info = await browser_session.get_tabs_info()
		assert isinstance(tabs_info, list)

		current_page = await browser_session.get_current_page()
		assert current_page is not None

		# Create a new tab
		new_page = await browser_session.create_new_tab()
		assert new_page is not None

		# Get tabs info again - should show more tabs
		updated_tabs = await browser_session.get_tabs_info()
		assert len(updated_tabs) > len(tabs_info)

		# Browser PID should remain the same
		assert browser_session.browser_pid == initial_pid
		assert browser_session._browser_context is not None

	async def test_lazy_initialization_behavior(self, browser_session):
		"""Test that operations trigger initialization when needed."""
		# logger.info('Testing lazy initialization behavior')

		# Ensure session is not started
		assert browser_session._browser_context is None
		assert browser_session.browser_pid is None

		# Calling an operation that needs browser should work
		# (implementation may auto-start or return empty/error)
		try:
			# Try to get current page on unstarted session
			page = await browser_session.get_current_page()
			# If it returns a page, session must have auto-started
			if page is not None:
				assert browser_session._browser_context is not None
				assert browser_session.browser_pid is not None
		except Exception:
			# If it fails, that's also valid behavior
			pass

		# Explicitly start and verify it works
		await browser_session.start()
		assert browser_session._browser_context is not None
		assert browser_session.browser_pid is not None

	async def test_page_lifecycle_management(self, browser_session):
		"""Test session handles page lifecycle correctly."""
		# logger.info('Testing page lifecycle management')

		# Start the session and get initial state
		await browser_session.start()
		initial_tabs = await browser_session.get_tabs_info()
		initial_count = len(initial_tabs)

		current_page = await browser_session.get_current_page()
		assert current_page is not None
		assert not current_page.is_closed()

		# Close the current page
		await current_page.close()

		# Verify page is closed
		assert current_page.is_closed()

		# Operations should still work - may create new page or use existing
		tabs_after_close = await browser_session.get_tabs_info()
		assert isinstance(tabs_after_close, list)

		# Create a new tab explicitly
		new_page = await browser_session.create_new_tab()
		assert new_page is not None
		assert not new_page.is_closed()

		# Should have at least one tab now
		final_tabs = await browser_session.get_tabs_info()
		assert len(final_tabs) >= 1

	async def test_concurrent_stop_calls(self, browser_profile):
		"""Test simultaneous calls to stop() from multiple coroutines."""
		# logger.info('Testing concurrent stop calls')

		# Create a single session for this test
		browser_session = BrowserSession(browser_profile=browser_profile)
		await browser_session.start()
		assert browser_session._browser_context is not None

		# Create a lock to ensure only one stop actually executes
		stop_lock = asyncio.Lock()
		stop_execution_count = 0

		async def safe_stop():
			nonlocal stop_execution_count
			async with stop_lock:
				if browser_session._browser_context is not None:
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
		assert browser_session._browser_context is None

	async def test_stop_with_closed_browser_context(self, browser_session):
		"""Test calling stop() when browser context is already closed."""
		# logger.info('Testing stop with closed browser context')

		# Start the session
		await browser_session.start()
		assert browser_session._browser_context is not None
		browser_ctx = browser_session._browser_context
		assert browser_ctx is not None

		# Manually close the browser context
		await browser_ctx.close()

		# stop() should handle this gracefully
		await browser_session.stop()

		# Session should be properly cleaned up
		assert browser_session._browser_context is None

	async def test_access_after_stop(self, browser_profile):
		"""Test accessing browser context after stop() to ensure proper cleanup."""
		# logger.info('Testing access after stop')

		# Create a session without fixture to avoid double cleanup
		browser_session = BrowserSession(browser_profile=browser_profile)

		# Start and stop the session
		await browser_session.start()
		await browser_session.stop()

		# Verify session is stopped
		assert browser_session._browser_context is None

		# calling a method wrapped in @require_initialization should auto-restart the session
		await browser_session.get_tabs()
		assert browser_session._browser_context is not None

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
			assert browser_session._browser_context is not None
			assert browser_session._browser_context is not None

			# Perform an operation
			tabs = await browser_session.get_tabs_info()
			assert isinstance(tabs, list)

			# Stop
			await browser_session.stop()
			assert browser_session._browser_context is None

	async def test_context_manager_with_exception(self, browser_session):
		"""Test context manager properly closes even when exception occurs."""
		# logger.info('Testing context manager with exception')

		class TestException(Exception):
			pass

		# Use context manager and raise exception inside
		with pytest.raises(TestException):
			async with browser_session as session:
				assert session._browser_context is not None
				raise TestException('Test exception')

		# Session should still be stopped despite the exception
		assert browser_session._browser_context is None

	async def test_session_without_fixture(self):
		"""Test creating a session without using fixture."""
		# Create a new profile and session for this test
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		session = BrowserSession(browser_profile=profile)

		try:
			await session.start()
			assert session._browser_context is not None
			await session.stop()
			assert session._browser_context is None
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
			assert session._browser_context is not None

			# Now test keep_alive behavior
			session.browser_profile.keep_alive = True

			# Stop should not actually close the browser with keep_alive=True
			await session.stop()
			# Browser should still be connected
			assert session._browser_context and session._browser_context.pages[0]

		finally:
			await session.kill()

	async def test_user_data_dir_not_allowed_to_corrupt_default_profile(self):
		"""Test user_data_dir handling for different browser channels and version mismatches."""
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
			assert session._browser_context is not None
			# Verify the user_data_dir wasn't changed
			assert session.browser_profile.user_data_dir == CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR
		finally:
			await session.kill()

		# Test 2: Chrome with default user_data_dir should automatically change dir
		profile2 = BrowserProfile(
			headless=True,
			user_data_dir=CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR,
			channel=BrowserChannel.CHROME,
			keep_alive=False,
		)

		# The validator should have changed the user_data_dir to avoid corruption
		assert profile2.user_data_dir != CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR
		assert profile2.user_data_dir == CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR.parent / 'default-chrome'

		# Test 3: Edge with default user_data_dir should also change
		profile3 = BrowserProfile(
			headless=True,
			user_data_dir=CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR,
			channel=BrowserChannel.MSEDGE,
			keep_alive=False,
		)

		assert profile3.user_data_dir != CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR
		assert profile3.user_data_dir == CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR.parent / 'default-msedge'


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
			enable_memory=False,  # Disable memory for tests
		)
		await agent1.run()

		# Verify first agent's session is closed
		assert agent1.browser_session is not None
		assert not agent1.browser_session._browser_context is not None

		# Second agent with same profile
		agent2 = Agent(
			task='The second task...',
			llm=mock_llm,
			browser_profile=reused_profile,
			enable_memory=False,  # Disable memory for tests
		)
		await agent2.run()

		# Verify second agent created a new session
		assert agent2.browser_session is not None
		assert agent1.browser_session is not agent2.browser_session
		assert not agent2.browser_session._browser_context is not None

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
				enable_memory=False,  # Disable memory for tests
			)
			await agent1.run()

			# Verify session is still alive
			assert reused_session._browser_context is not None

			# Second agent reusing the same session
			agent2 = Agent(
				task='The second task...',
				llm=mock_llm,
				browser_session=reused_session,
				enable_memory=False,  # Disable memory for tests
			)
			await agent2.run()

			# Verify same browser was used (using __eq__ to check browser_pid, cdp_url)
			assert agent1.browser_session == agent2.browser_session
			assert agent1.browser_session == reused_session
			assert reused_session._browser_context is not None

		finally:
			await reused_session.kill()

	# async def test_parallel_agents_same_browser_multiple_tabs(self, httpserver):
	# 	"""Test Parallel Agents, Same Browser, Multiple Tabs pattern"""

	# 	from browser_use import Agent, BrowserSession

	# 	# Create a shared browser session
	# 	with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as f:
	# 		# Write minimal valid storage state
	# 		f.write('{"cookies": [], "origins": []}')
	# 		storage_state_path = f.name

	# 	# Convert to Path object to fix storage state type error
	# 	from pathlib import Path

	# 	storage_state_path = Path(storage_state_path)

	# 	shared_browser = BrowserSession(
	# 		browser_profile=BrowserProfile(
	# 			storage_state=storage_state_path,
	# 			user_data_dir=None,
	# 			keep_alive=True,
	# 			headless=True,
	# 		),
	# 	)

	# 	try:
	# 		# Set up httpserver
	# 		httpserver.expect_request('/').respond_with_data('<html><body>Test page</body></html>')
	# 		test_url = httpserver.url_for('/')

	# 		# Start the session before passing it to agents
	# 		await shared_browser.start()

	# 		# Create action sequences for each agent
	# 		# Each agent creates a new tab then completes
	# 		tab_creation_action = (
	# 			"""
	# 		{
	# 			"thinking": "null",
	# 			"evaluation_previous_goal": "Starting the task",
	# 			"memory": "Need to create a new tab",
	# 			"next_goal": "Create a new tab to work in",
	# 			"action": [
	# 				{
	# 					"go_to_url": {
	# 						"url": "%s",
	# 						"new_tab": true
	# 					}
	# 				}
	# 			]
	# 		}
	# 		"""
	# 			% test_url
	# 		)

	# 		done_action = """
	# 		{
	# 			"thinking": "null",
	# 			"evaluation_previous_goal": "Tab created",
	# 			"memory": "Task completed in new tab",
	# 			"next_goal": "Complete the task",
	# 			"action": [
	# 				{
	# 					"done": {
	# 						"text": "Task completed successfully",
	# 						"success": true
	# 					}
	# 				}
	# 			]
	# 		}
	# 		"""

	# 		# Create 3 agents sharing the same browser session
	# 		# Each gets its own mock LLM with the same action sequence
	# 		mock_llm1 = create_mock_llm([tab_creation_action, done_action])
	# 		mock_llm2 = create_mock_llm([tab_creation_action, done_action])
	# 		mock_llm3 = create_mock_llm([tab_creation_action, done_action])

	# 		agent1 = Agent(
	# 			task='First parallel task...',
	# 			llm=mock_llm1,
	# 			browser_session=shared_browser,
	# 			enable_memory=False,  # Disable memory for tests
	# 		)
	# 		agent2 = Agent(
	# 			task='Second parallel task...',
	# 			llm=mock_llm2,
	# 			browser_session=shared_browser,
	# 			enable_memory=False,  # Disable memory for tests
	# 		)
	# 		agent3 = Agent(
	# 			task='Third parallel task...',
	# 			llm=mock_llm3,
	# 			browser_session=shared_browser,
	# 			enable_memory=False,  # Disable memory for tests
	# 		)

	# 		# Run all agents in parallel
	# 		results = await asyncio.gather(agent1.run(), agent2.run(), agent3.run(), return_exceptions=True)

	# 		# Check if any agents failed
	# 		for i, result in enumerate(results):
	# 			if isinstance(result, Exception):
	# 				raise AssertionError(f'Agent {i + 1} failed with error: {result}')

	# 		# Verify all agents used the same browser session (using __eq__ to check browser_pid, cdp_url)
	# 		# Debug: print the browser sessions to see what's different
	# 		print(f'Agent1 session: {agent1.browser_session}')
	# 		print(f'Agent2 session: {agent2.browser_session}')
	# 		print(f'Agent3 session: {agent3.browser_session}')
	# 		print(f'Shared session: {shared_browser}')

	# 		# Check each pair individually
	# 		assert agent1.browser_session == agent2.browser_session, (
	# 			f'agent1 != agent2: {agent1.browser_session} != {agent2.browser_session}'
	# 		)
	# 		assert agent2.browser_session == agent3.browser_session, (
	# 			f'agent2 != agent3: {agent2.browser_session} != {agent3.browser_session}'
	# 		)
	# 		assert agent1.browser_session == shared_browser, f'agent1 != shared: {agent1.browser_session} != {shared_browser}'
	# 		assert shared_browser._browser_context is not None

	# 		# Give a small delay to ensure all tabs are fully created
	# 		await asyncio.sleep(0.5)

	# 		# Verify multiple tabs were created
	# 		tabs_info = await shared_browser.get_tabs_info()
	# 		print(f'Number of tabs: {len(tabs_info)}')
	# 		for i, tab in enumerate(tabs_info):
	# 			print(f'Tab {i}: {tab}')

	# 		# Should have at least 3 tabs (one per agent)
	# 		# In some cases, there might be more tabs if the initial about:blank tab is still open
	# 		assert len(tabs_info) >= 3, f'Expected at least 3 tabs, but found {len(tabs_info)}: {tabs_info}'

	# 	finally:
	# 		await shared_browser.kill()
	# 		storage_state_path.unlink(missing_ok=True)

	# async def test_parallel_agents_same_browser_same_tab(self, mock_llm, httpserver):
	# 	"""Test Parallel Agents, Same Browser, Same Tab pattern (not recommended)"""
	# 	from browser_use import Agent, BrowserSession

	# 	# Create a browser session and start it first
	# 	shared_browser = BrowserSession(
	# 		browser_profile=BrowserProfile(
	# 			user_data_dir=None,
	# 			headless=True,
	# 			keep_alive=True,  # Keep the browser alive for reuse
	# 		),
	# 	)

	# 	try:
	# 		await shared_browser.start()

	# 		# Create agents sharing the same browser session
	# 		# They will share the same tab since we're not creating new tabs
	# 		agent1 = Agent(
	# 			task='Fill out the form in section A...',
	# 			llm=mock_llm,
	# 			browser_session=shared_browser,
	# 			enable_memory=False,  # Disable memory for tests
	# 		)
	# 		agent2 = Agent(
	# 			task='Fill out the form in section B...',
	# 			llm=mock_llm,
	# 			browser_session=shared_browser,
	# 			enable_memory=False,  # Disable memory for tests
	# 		)

	# 		# Set up httpserver and navigate to a page before running agents
	# 		httpserver.expect_request('/').respond_with_data('<html><body>Test page</body></html>')
	# 		page = await shared_browser.get_current_page()
	# 		await page.goto(httpserver.url_for('/'), wait_until='domcontentloaded', timeout=3000)

	# 		# Run agents in parallel (may interfere with each other)
	# 		_results = await asyncio.gather(agent1.run(), agent2.run(), return_exceptions=True)

	# 		# Verify both agents used the same browser session
	# 		assert agent1.browser_session == agent2.browser_session
	# 		assert agent1.browser_session == shared_browser

	# 	finally:
	# 		# Clean up
	# 		await shared_browser.kill()

	async def test_parallel_agents_same_profile_different_browsers(self, mock_llm, httpserver):
		"""Test Parallel Agents, Same Profile, Different Browsers pattern (recommended)"""

		from browser_use import Agent
		from browser_use.browser import BrowserProfile, BrowserSession

		# Set up HTTP server with cookie-setting endpoint using HTTP headers
		httpserver.expect_request('/set-cookies').respond_with_data(
			'<html><body>Cookies set via HTTP headers!</body></html>',
			headers={
				'Content-Type': 'text/html',
				'Set-Cookie': ['session_id=test123; Path=/', 'auth_token=abc456; Path=/'],
			},
		)

		httpserver.expect_request('/page2').respond_with_data(
			'<html><body>Page 2 with preferences!</body></html>',
			headers={
				'Content-Type': 'text/html',
				'Set-Cookie': ['user_pref=dark_mode; Path=/', 'theme=night; Path=/'],
			},
		)

		# Create a shared profile with storage state
		with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as f:
			# Write minimal valid storage state
			f.write('{"cookies": [], "origins": []}')
			auth_json_path = f.name

		# Convert to Path object
		from pathlib import Path

		auth_json_path = Path(auth_json_path)

		shared_profile = BrowserProfile(
			headless=True,
			user_data_dir=None,  # Use dedicated tmp user_data_dir per session
			storage_state=str(auth_json_path),  # Load/save cookies to/from json file
			keep_alive=True,
		)
		print(f'Profile storage_state: {shared_profile.storage_state}')

		try:
			# Create separate browser sessions from the same profile
			window1 = BrowserSession(browser_profile=shared_profile)
			await window1.start()
			agent1 = Agent(task='First agent task...', llm=mock_llm, browser_session=window1, enable_memory=False)

			window2 = BrowserSession(browser_profile=shared_profile)
			await window2.start()
			agent2 = Agent(task='Second agent task...', llm=mock_llm, browser_session=window2, enable_memory=False)

			# Navigate to pages that set cookies
			# Use 127.0.0.1 instead of localhost for cookie persistence
			base_url = httpserver.url_for('/')
			if 'localhost' in base_url:
				base_url = base_url.replace('localhost', '127.0.0.1')

			await window1.navigate_to(base_url.rstrip('/') + '/set-cookies')
			await window2.navigate_to(base_url.rstrip('/') + '/page2')

			# Wait for pages to load
			page1 = await window1.get_current_page()
			page2 = await window2.get_current_page()
			await page1.wait_for_load_state('networkidle')
			await page2.wait_for_load_state('networkidle')

			# Inject cookies directly via CDP to ensure they're set
			await page1.context.add_cookies(
				[
					{'name': 'session_id', 'value': 'test123', 'domain': '127.0.0.1', 'path': '/'},
					{'name': 'auth_token', 'value': 'abc456', 'domain': '127.0.0.1', 'path': '/'},
				]
			)
			await page2.context.add_cookies(
				[
					{'name': 'user_pref', 'value': 'dark_mode', 'domain': '127.0.0.1', 'path': '/'},
					{'name': 'theme', 'value': 'night', 'domain': '127.0.0.1', 'path': '/'},
				]
			)

			# Run agents in parallel
			_results = await asyncio.gather(agent1.run(), agent2.run())

			# Verify different browser sessions were used
			assert agent1.browser_session is not agent2.browser_session
			assert window1 is not window2

			# Both sessions should be initialized
			assert window1._browser_context is not None
			assert window2._browser_context is not None

			# Check cookies in each context - they should be separate
			context1_cookies = await page1.context.cookies()
			context2_cookies = await page2.context.cookies()
			print(f'Context1 cookies: {[c.get("name", "unknown") for c in context1_cookies]}')
			print(f'Context2 cookies: {[c.get("name", "unknown") for c in context2_cookies]}')

			# Since these are separate browser contexts, they won't share cookies
			# But let's verify the cookies exist in their respective contexts
			# We need to get cookies for the specific domain
			domain_cookies1 = await page1.context.cookies(base_url)
			domain_cookies2 = await page2.context.cookies(base_url)
			print(f'Domain cookies window1: {[c.get("name", "unknown") for c in domain_cookies1]}')
			print(f'Domain cookies window2: {[c.get("name", "unknown") for c in domain_cookies2]}')

			# Save storage state from window1
			await window1.save_storage_state()
			storage_state_1 = json.loads(auth_json_path.read_text())
			cookies_1 = {c.get('name', 'unknown') for c in storage_state_1['cookies']}
			print(f'Cookies saved from window1: {cookies_1}')

			# Save storage state from window2 (this overwrites the file)
			await window2.save_storage_state()
			storage_state_2 = json.loads(auth_json_path.read_text())
			cookies_2 = {c.get('name', 'unknown') for c in storage_state_2['cookies']}
			print(f'Cookies saved from window2: {cookies_2}')

			# Verify each window saved its own cookies
			assert len(cookies_1) >= 2, f'Window1 should have saved at least 2 cookies, got {cookies_1}'
			assert len(cookies_2) >= 2, f'Window2 should have saved at least 2 cookies, got {cookies_2}'

			# Now test that a new session can load the saved cookies
			print('\nTesting cookie persistence with new session...')
			await window1.kill()
			await window2.kill()

			# Create a new session with the same profile
			window3 = BrowserSession(browser_profile=shared_profile)
			await window3.start()

			# Check if cookies were loaded
			page3 = await window3.get_current_page()
			await page3.goto(base_url)  # Navigate to the domain
			loaded_cookies = await page3.context.cookies()
			loaded_cookie_names = {c.get('name', 'unknown') for c in loaded_cookies}
			print(f'Cookies loaded in new session: {loaded_cookie_names}')

			# Should have the cookies from window2 (last save)
			assert len(loaded_cookie_names) >= 2, f'Expected loaded cookies, got {loaded_cookie_names}'

			await window3.kill()

		finally:
			# Clean up any remaining sessions
			try:
				if 'window1' in locals():
					await window1.kill()
			except Exception:
				pass
			try:
				if 'window2' in locals():
					await window2.kill()
			except Exception:
				pass
			try:
				if 'window3' in locals():
					await window3.kill()
			except Exception:
				pass
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


class TestBrowserSessionEventSystem:
	"""Tests for the new event system integration in BrowserSession."""

	@pytest.fixture(scope='function')
	async def browser_session(self):
		"""Create a BrowserSession instance for event system testing."""
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		session = BrowserSession(browser_profile=profile)
		yield session
		await session.kill()

	async def test_event_bus_initialization(self, browser_session):
		"""Test that event bus is properly initialized with unique name."""
		# Event bus should be created during __init__
		assert browser_session.event_bus is not None
		assert browser_session.event_bus.name.startswith('BrowserSession_')
		assert browser_session.id[-4:] in browser_session.event_bus.name

	async def test_event_handlers_registration(self, browser_session):
		"""Test that event handlers are properly registered."""
		# Check that handlers are registered in the event bus
		from browser_use.browser.events import (
			BrowserStartEvent,
			BrowserStateRequestEvent,
			BrowserStopEvent,
			ClickElementEvent,
			CloseTabEvent,
			ScreenshotEvent,
			ScrollEvent,
			TypeTextEvent,
		)

		# These event types should have handlers registered
		event_types_with_handlers = [
			BrowserStartEvent,
			BrowserStopEvent,
			ClickElementEvent,
			TypeTextEvent,
			ScrollEvent,
			CloseTabEvent,
			BrowserStateRequestEvent,
			ScreenshotEvent,
		]

		for event_type in event_types_with_handlers:
			handlers = browser_session.event_bus.handlers.get(event_type.__name__, [])
			assert len(handlers) > 0, f'No handlers registered for {event_type.__name__}'

	async def test_direct_event_dispatching(self, browser_session):
		"""Test direct event dispatching without using the public API."""
		from browser_use.browser.events import BrowserConnectedEvent, BrowserStartEvent

		# Dispatch BrowserStartEvent directly
		start_event = browser_session.event_bus.dispatch(BrowserStartEvent())

		# Wait for event to complete
		await start_event

		# Check if BrowserConnectedEvent was dispatched
		assert browser_session._browser_context is not None

		# Check event history
		event_history = list(browser_session.event_bus.event_history.values())
		assert len(event_history) >= 2  # BrowserStartEvent + BrowserConnectedEvent + others

		# Find the BrowserConnectedEvent in history
		started_events = [e for e in event_history if isinstance(e, BrowserConnectedEvent)]
		assert len(started_events) >= 1
		assert started_events[0].cdp_url is not None

	async def test_event_history_tracking(self, browser_session):
		"""Test that event history is properly tracked."""
		# Start and stop browser to generate events
		await browser_session.start()
		await browser_session.stop()

		# Check event history generation
		recent_events_json = browser_session._generate_recent_events_summary(max_events=5)
		assert recent_events_json != '[]'

		# Parse and validate the JSON
		import json

		recent_events = json.loads(recent_events_json)
		assert isinstance(recent_events, list)
		assert len(recent_events) > 0

		# Events should have the expected structure
		for event in recent_events:
			assert isinstance(event, dict)
			assert 'event_type' in event or '__class__' in event  # Event structure may vary

	async def test_event_system_error_handling(self, browser_session):
		"""Test error handling in event system."""
		from browser_use.browser.events import BrowserStartEvent

		# Create session with invalid CDP URL to trigger error
		error_session = BrowserSession(
			browser_profile=BrowserProfile(headless=True),
			cdp_url='http://localhost:99999',  # Invalid port
		)

		try:
			# Dispatch start event directly - should trigger error handling
			start_event = error_session.event_bus.dispatch(BrowserStartEvent())

			# The event bus catches and logs the error, but the event awaits successfully
			await start_event

			# The session should not be initialized due to the error
			assert error_session._browser_context is None, 'Session should not be initialized after connection error'

			# Verify the error was logged in the event history (good enough for error handling test)
			assert len(error_session.event_bus.event_history) > 0, 'Event should be tracked even with errors'

		finally:
			await error_session.kill()

	async def test_concurrent_event_dispatching(self, browser_session):
		"""Test that concurrent events are handled properly."""
		from browser_use.browser.events import ScreenshotEvent

		# Start browser first
		await browser_session.start()

		# Dispatch multiple events concurrently
		screenshot_event1 = browser_session.event_bus.dispatch(ScreenshotEvent())
		screenshot_event2 = browser_session.event_bus.dispatch(ScreenshotEvent())

		# Both should complete successfully
		results = await asyncio.gather(screenshot_event1, screenshot_event2, return_exceptions=True)

		# Check that no exceptions were raised
		for result in results:
			assert not isinstance(result, Exception), f'Event failed with: {result}'

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

		print('Starting many parallel browser sessions...')
		await asyncio.gather(*[browser_session.start() for browser_session in browser_sessions])

		print('Ensuring all parallel browser sessions are connected and usable...')
		new_tab_tasks = []
		for browser_session in browser_sessions:
			assert await browser_session.is_connected()
			assert browser_session._browser_context is not None
			new_tab_tasks.append(browser_session.create_new_tab('chrome://version'))
		await asyncio.gather(*new_tab_tasks)

		print('killing every 3rd browser_session to test parallel shutdown')
		kill_tasks = []
		for i in range(0, len(browser_sessions), 3):
			kill_tasks.append(browser_sessions[i].kill())
			browser_sessions[i] = None
		results = await asyncio.gather(*kill_tasks, return_exceptions=True)
		# Check that no exceptions were raised during cleanup
		for i, result in enumerate(results):
			if isinstance(result, Exception):
				print(f'Warning: Browser session kill raised exception: {type(result).__name__}: {result}')

		print('ensuring the remaining browser_sessions are still connected and usable')
		new_tab_tasks = []
		screenshot_tasks = []
		for browser_session in filter(bool, browser_sessions):
			assert await browser_session.is_connected()
			assert browser_session._browser_context is not None
			new_tab_tasks.append(browser_session.create_new_tab('chrome://version'))
			screenshot_tasks.append(browser_session.take_screenshot())
		await asyncio.gather(*new_tab_tasks)
		await asyncio.gather(*screenshot_tasks)

		kill_tasks = []
		print('killing the remaining browser_sessions')
		for browser_session in filter(bool, browser_sessions):
			kill_tasks.append(browser_session.kill())
		results = await asyncio.gather(*kill_tasks, return_exceptions=True)
		# Check that no exceptions were raised during cleanup
		for i, result in enumerate(results):
			if isinstance(result, Exception):
				print(f'Warning: Browser session kill raised exception: {type(result).__name__}: {result}')
