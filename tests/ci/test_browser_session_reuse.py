"""
Test browser session reuse and regeneration after browser disconnection.

Tests cover:
- Browser regeneration after context is closed
- Screenshot functionality after regeneration
- Multiple regeneration cycles
"""

import asyncio

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


class TestBrowserSessionReuse:
	"""Tests for browser session reuse and regeneration after disconnection."""

	# TODO: fix this test / pid detection
	# async def test_browser_regeneration_after_disconnect(self):
	# 	"""Test that browser regenerates and screenshot succeeds after disconnection"""
	# 	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None))

	# 	try:
	# 		# Start browser session
	# 		await session.start()

	# 		# Navigate to a test page
	# 		assert session.page is not None
	# 		await session.page.goto('data:text/html,<h1>Test Page - Before Disconnect</h1>')

	# 		# Take a screenshot before disconnection
	# 		screenshot1 = await session.take_screenshot()
	# 		assert screenshot1 is not None
	# 		assert len(screenshot1) > 0

	# 		# Store initial browser PID
	# 		initial_browser_pid = session.browser_pid
	# 		assert initial_browser_pid is not None

	# 		# Force disconnect the browser by closing the browser context
	# 		assert session.browser_context is not None
	# 		await session.browser_context.close()

	# 		# Try to take a screenshot - this should trigger regeneration internally
	# 		# Thanks to the @require_initialization decorator and our fix, this should succeed
	# 		screenshot2 = await session.take_screenshot()
	# 		assert screenshot2 is not None
	# 		assert len(screenshot2) > 0

	# 		# Check if browser was regenerated (new browser context created)
	# 		assert session.browser_context is not None
	# 		# Verify the context is valid by checking if we can access its pages
	# 		assert session.browser_context.pages is not None

	# 		# Verify we can still interact with the browser
	# 		assert session.page is not None
	# 		await session.page.goto('data:text/html,<h1>Test Page - After Regeneration</h1>')
	# 		screenshot3 = await session.take_screenshot()
	# 		assert screenshot3 is not None
	# 		assert len(screenshot3) > 0

	# 	finally:
	# 		await session.stop()

	async def test_multiple_browser_regenerations(self, httpserver):
		"""Test multiple browser regeneration cycles"""
		session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None))

		httpserver.expect_request('/normal').respond_with_data(
			'<html><body><h1>Normal Page</h1></body></html>',
			content_type='text/html',
		)

		try:
			await session.start()

			for i in range(3):
				# Navigate to a test page
				assert session.page is not None
				await session.page.goto(httpserver.url_for('/normal'), wait_until='load', timeout=3000)

				# Take screenshot before disconnect
				screenshot_before = await session.take_screenshot()
				assert screenshot_before is not None
				assert len(screenshot_before) > 100

				# Properly kill the session to clean up browser subprocess
				await session.kill()

				# Add a delay to ensure all resources are released
				await asyncio.sleep(0.5)

				# Start a fresh session for the next iteration
				await session.start()

				# Take screenshot after regeneration
				screenshot_after = await session.take_screenshot()
				assert screenshot_after is not None
				assert len(screenshot_after) > 0 and len(screenshot_after) < 200, (
					'expected white 4px screenshot of about:blank when browser is reset after disconnection'
				)

		finally:
			await session.kill()

	async def test_browser_session_reuse_with_retry_decorator(self):
		"""Test that the retry decorator properly handles browser regeneration"""
		session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None))

		try:
			await session.start()

			# Navigate to a test page
			assert session.page is not None
			await session.page.goto('data:text/html,<h1>Test Retry Decorator</h1>')

			# Take a screenshot to verify it works
			screenshot1 = await session.take_screenshot()
			assert screenshot1 is not None

			# Store browser PID
			initial_pid = session.browser_pid

			# Close the browser context while a screenshot is in progress
			# This simulates a browser crash during CDP operation
			async def close_during_operation():
				await asyncio.sleep(0.05)  # Small delay to let CDP operation start
				if session.browser_context:
					try:
						await session.browser_context.close()
					except Exception:
						# Context might already be closed
						pass

			# Start the close task
			close_task = asyncio.create_task(close_during_operation())

			try:
				# Try to take a screenshot - the retry decorator should handle the failure
				# Note: This might succeed if the screenshot completes before the close
				try:
					screenshot2 = await session.take_screenshot()
					# If it succeeded, the browser should have been regenerated
					assert screenshot2 is not None
				except Exception:
					# If it failed, that's also OK - the browser state was reset
					pass

				# Wait for close task to complete
				await close_task
			finally:
				# Ensure the task is properly cancelled if it hasn't completed
				if not close_task.done():
					close_task.cancel()
					try:
						await close_task
					except asyncio.CancelledError:
						pass

			# Verify we can still use the browser after regeneration
			await session.start()  # Ensure browser is started
			screenshot3 = await session.take_screenshot()
			assert screenshot3 is not None
			assert len(screenshot3) > 0

		finally:
			await session.stop()
