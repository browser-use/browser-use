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
import logging

import pytest

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

# Set up test logging
logger = logging.getLogger('browser_session_start_tests')
# logger.setLevel(logging.DEBUG)


class TestBrowserSessionStart:
	"""Tests for BrowserSession.start() method initialization and concurrency."""

	@pytest.fixture
	async def browser_profile(self):
		"""Create and provide a BrowserProfile with headless mode."""
		profile = BrowserProfile(headless=True, user_data_dir=None)
		yield profile

	@pytest.fixture
	async def browser_session(self, browser_profile):
		"""Create a BrowserSession instance without starting it."""
		session = BrowserSession(browser_profile=browser_profile)
		yield session
		# Cleanup: ensure session is stopped
		try:
			await session.stop()
		except Exception:
			pass

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

	async def test_start_with_keep_alive_profile(self):
		"""Test start/stop behavior with keep_alive=True profile."""
		# logger.info('Testing start with keep_alive profile')

		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=True)
		session = BrowserSession(browser_profile=profile)

		try:
			await session.start()
			assert session.initialized is True

			# Stop should not actually close the browser with keep_alive=True
			await session.stop()
			# initialized flag should still be False after stop()
			assert session.initialized is False

		finally:
			# Force cleanup for test
			session.browser_profile.keep_alive = False
			await session.stop()

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
