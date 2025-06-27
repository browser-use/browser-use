"""
Test browser resource ownership when BrowserSession is copied.
"""

import asyncio
import gc

from browser_use import Agent, BrowserProfile, BrowserSession
from tests.ci.conftest import create_mock_llm


class TestBrowserOwnership:
	"""Test that browser resource ownership is properly managed when sessions are copied."""

	async def test_copied_session_doesnt_own_browser(self):
		"""Test that copied BrowserSession instances don't own the browser resources."""
		# Create original browser session
		original = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				keep_alive=False,  # Should still work even with keep_alive=False
				user_data_dir=None,
			)
		)

		# Verify original owns the browser
		assert original._owns_browser_resources is True

		# Create a copy
		copy1 = original.model_copy()

		# Verify copy doesn't own the browser
		assert copy1._owns_browser_resources is False
		assert copy1._original_browser_session is original

		# Create another copy
		copy2 = original.model_copy()
		assert copy2._owns_browser_resources is False
		assert copy2._original_browser_session is original

	async def test_agent_copies_dont_kill_browser(self, httpserver):
		"""Test that when agents use a browser session, they don't kill the browser when garbage collected."""
		# Set up test page
		httpserver.expect_request('/test').respond_with_data(
			'<html><body><h1>Test Page</h1><button>Click me</button></body></html>'
		)

		# Create original browser session with keep_alive=True to prevent agent from closing it
		original_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				keep_alive=True,  # Keep browser alive when agents complete
				user_data_dir=None,
			)
		)
		await original_session.start()
		initial_browser_pid = original_session.browser_pid
		# assert initial_browser_pid is not None, 'Browser PID should always exist after launch'

		# Create first agent that will use the session
		async def run_agent1():
			agent1 = Agent(
				task='Navigate to test page',
				llm=create_mock_llm(
					[
						f'''{{
						"thinking": "Navigating to test page",
						"evaluation_previous_goal": "Starting task",
						"memory": "Need to navigate",
						"next_goal": "Navigate to test page",
						"action": [
							{{
								"go_to_url": {{
									"url": "{httpserver.url_for('/test')}"
								}}
							}}
						]
					}}'''
					]
				),
				browser_session=original_session,
			)
			await agent1.run(max_steps=1)
			# agent1 uses the original session directly (no copy when owns_browser_resources=True)
			assert agent1.browser_session is not None
			assert agent1.browser_session is original_session
			assert agent1.browser_session._owns_browser_resources is True
			# Browser should still be running
			assert original_session.browser_pid == initial_browser_pid

		await run_agent1()

		# Force garbage collection to ensure agent1 is cleaned up
		gc.collect()
		await asyncio.sleep(0.1)

		# Browser should still be alive because the original session still owns it
		assert await original_session.is_connected(restart=False)
		assert original_session.browser_pid == initial_browser_pid

		# Create second agent
		async def run_agent2():
			agent2 = Agent(
				task='Click the button',
				llm=create_mock_llm(
					[
						"""{
						"thinking": "Clicking button",
						"evaluation_previous_goal": "On test page",
						"memory": "Need to click button",
						"next_goal": "Click button",
						"action": [
							{
								"click_element_by_index": {
									"index": 0
								}
							}
						]
					}"""
					]
				),
				browser_session=original_session,
			)
			await agent2.run(max_steps=1)
			assert agent2.browser_session is not None
			assert agent2.browser_session is original_session
			assert agent2.browser_session._owns_browser_resources is True

		await run_agent2()

		# Force garbage collection again
		gc.collect()
		await asyncio.sleep(0.1)

		# Browser should still be alive
		assert await original_session.is_connected(restart=False)
		assert original_session.browser_pid == initial_browser_pid

		# Now clean up the original - use kill() since keep_alive=True
		await original_session.kill()

		# Browser should be disconnected now
		assert not await original_session.is_connected(restart=False)

	async def test_shared_browser_recovery_after_disconnect(self, httpserver):
		"""Test that copied sessions can recover if the shared browser is disconnected."""
		# Set up test page
		httpserver.expect_request('/test').respond_with_data('<html><body><h1>Recovery Test</h1></body></html>')

		# Create original browser session
		original_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				keep_alive=True,  # Keep alive for sharing
				user_data_dir=None,
			)
		)
		await original_session.start()

		# Create a copy (simulating what Agent does)
		copied_session = original_session.model_copy()
		copied_session.playwright = original_session.playwright
		copied_session.browser = original_session.browser
		copied_session.browser_context = original_session.browser_context
		copied_session.agent_current_page = original_session.agent_current_page

		# Verify copy doesn't own the browser
		assert copied_session._owns_browser_resources is False

		# Navigate using the copy
		await copied_session.create_new_tab(httpserver.url_for('/test'))

		# Force disconnect the browser context
		assert original_session.browser_context is not None
		await original_session.browser_context.close()

		# Try to use the copy - it should recover
		await copied_session.start()  # Should reconnect
		screenshot = await copied_session.take_screenshot()
		assert screenshot is not None
		assert len(screenshot) > 0

		# Clean up
		await original_session.kill()

	async def test_multiple_copies_single_owner(self):
		"""Test that multiple copies all reference the same original owner."""
		original = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
			)
		)

		# Create multiple copies
		copies = []
		for i in range(5):
			copy = original.model_copy()
			copies.append(copy)

			# Verify each copy doesn't own the browser
			assert copy._owns_browser_resources is False
			assert copy._original_browser_session is original

		# All copies should reference the same original
		for copy in copies:
			assert copy._original_browser_session is original

		# Only the original owns the browser
		assert original._owns_browser_resources is True
