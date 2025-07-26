"""
Simple test to verify that sequential agents can reuse the same BrowserSession
without it being closed prematurely due to garbage collection.
"""

import asyncio
import gc

from browser_use import Agent, BrowserProfile, BrowserSession
from tests.ci.conftest import create_mock_llm


class TestSequentialAgentsSimple:
	"""Test that sequential agents can properly reuse the same BrowserSession"""

	async def test_sequential_agents_share_browser_session_simple(self, httpserver):
		"""Test that multiple agents can reuse the same browser session without it being closed"""
		# Set up test HTML pages
		httpserver.expect_request('/page1').respond_with_data('<html><body><h1>Page 1</h1></body></html>')
		httpserver.expect_request('/page2').respond_with_data('<html><body><h1>Page 2</h1></body></html>')

		# Create a browser session with keep_alive=True
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				keep_alive=True,
				headless=True,
				user_data_dir=None,  # Use temporary directory
			)
		)
		await browser_session.start()

		# Verify browser is running
		initial_pid = browser_session.browser_pid
		# Browser PID detection may fail in CI environments
		# The important thing is that the browser is connected
		assert await browser_session.is_connected(restart=False)

		# Agent 1: Navigate to page 1
		agent1_actions = [
			f"""{{
				"thinking": "Navigating to page 1",
				"evaluation_previous_goal": "Starting task",
				"memory": "Need to navigate to page 1",
				"next_goal": "Navigate to page 1",
				"action": [
					{{"go_to_url": {{"url": "{httpserver.url_for('/page1')}", "new_tab": false}}}}
				]
			}}"""
		]

		agent1 = Agent(
			task='Navigate to page 1',
			llm=create_mock_llm(agent1_actions),
			browser_session=browser_session,
		)
		history1 = await agent1.run(max_steps=2)
		assert len(history1.history) >= 1
		assert history1.history[-1].state.url == httpserver.url_for('/page1')

		# Verify browser session is still alive
		assert browser_session.initialized
		if initial_pid is not None:
			assert browser_session.browser_pid == initial_pid

		# Delete agent1 and force garbage collection
		del agent1
		gc.collect()
		await asyncio.sleep(0.1)  # Give time for any async cleanup

		# Verify browser is STILL alive after garbage collection
		assert browser_session.initialized
		if initial_pid is not None:
			assert browser_session.browser_pid == initial_pid
		assert browser_session.browser_context is not None

		# Agent 2: Navigate to page 2
		agent2_actions = [
			f"""{{
				"thinking": "Navigating to page 2",
				"evaluation_previous_goal": "Previous agent successfully navigated",
				"memory": "Browser is still open, need to go to page 2",
				"next_goal": "Navigate to page 2",
				"action": [
					{{"go_to_url": {{"url": "{httpserver.url_for('/page2')}", "new_tab": false}}}}
				]
			}}"""
		]

		agent2 = Agent(
			task='Navigate to page 2',
			llm=create_mock_llm(agent2_actions),
			browser_session=browser_session,
		)
		history2 = await agent2.run(max_steps=2)
		assert len(history2.history) >= 1
		assert history2.history[-1].state.url == httpserver.url_for('/page2')

		# Verify browser session is still alive after second agent
		assert browser_session.initialized
		if initial_pid is not None:
			assert browser_session.browser_pid == initial_pid
		assert browser_session.browser_context is not None

		# Clean up
		await browser_session.kill()

	async def test_multiple_tabs_sequential_agents(self, httpserver):
		"""Test that sequential agents can work with multiple tabs"""
		# Set up test pages
		httpserver.expect_request('/tab1').respond_with_data('<html><body><h1>Tab 1</h1></body></html>')
		httpserver.expect_request('/tab2').respond_with_data('<html><body><h1>Tab 2</h1></body></html>')

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				keep_alive=True,
				headless=True,
				user_data_dir=None,  # Use temporary directory
			)
		)
		await browser_session.start()

		# Agent 1: Open two tabs
		agent1_actions = [
			f"""{{
				"thinking": "Opening two tabs",
				"evaluation_previous_goal": "Starting task",
				"memory": "Need to open two tabs",
				"next_goal": "Open tab 1 and tab 2",
				"action": [
					{{"go_to_url": {{"url": "{httpserver.url_for('/tab1')}", "new_tab": false}}}},
					{{"go_to_url": {{"url": "{httpserver.url_for('/tab2')}", "new_tab": true}}}}
				]
			}}"""
		]

		agent1 = Agent(
			task='Open two tabs',
			llm=create_mock_llm(agent1_actions),
			browser_session=browser_session,
		)
		await agent1.run(max_steps=2)

		# Verify 2 tabs are open
		assert len(browser_session.tabs) == 2
		# Agent1 should be on the second tab (tab2)
		assert agent1.browser_session is not None
		assert agent1.browser_session.agent_current_page is not None
		assert '/tab2' in agent1.browser_session.agent_current_page.url

		# Clean up agent1
		del agent1
		gc.collect()
		await asyncio.sleep(0.1)

		# Agent 2: Switch to first tab
		agent2_actions = [
			"""{
				"thinking": "Switching to first tab",
				"evaluation_previous_goal": "Two tabs are open",
				"memory": "Need to switch to tab 0",
				"next_goal": "Switch to tab 0",
				"action": [
					{"switch_tab": {"page_id": 0}}
				]
			}"""
		]

		agent2 = Agent(
			task='Switch to first tab',
			llm=create_mock_llm(agent2_actions),
			browser_session=browser_session,
		)
		history2 = await agent2.run(max_steps=3)

		# Verify agent2 is on the first tab
		assert agent2.browser_session is not None
		assert agent2.browser_session.agent_current_page is not None
		assert '/tab1' in agent2.browser_session.agent_current_page.url

		# Verify browser is still functional
		assert browser_session.initialized
		assert len(browser_session.tabs) == 2

		await browser_session.kill()
