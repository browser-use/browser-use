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
		# Get initial browser PID from local_browser_watchdog
		initial_pid = (
			browser_session._local_browser_watchdog._subprocess.pid
			if browser_session._local_browser_watchdog and browser_session._local_browser_watchdog._subprocess
			else None
		)
		# Browser PID detection may fail in CI environments
		# The important thing is that the browser is connected
		# Verify session is connected
		try:
			url = await browser_session.get_current_page_url()
			assert url is not None
		except Exception:
			assert False, 'Browser session is not connected'

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
		# Verify session is still connected (checking internal state for test)
		url = await browser_session.get_current_page_url()
		assert url is not None
		if initial_pid is not None:
			# Check browser PID is still the same
			current_pid = (
				browser_session._local_browser_watchdog._subprocess.pid
				if browser_session._local_browser_watchdog and browser_session._local_browser_watchdog._subprocess
				else None
			)
			assert current_pid == initial_pid

		# Delete agent1 and force garbage collection
		del agent1
		gc.collect()
		await asyncio.sleep(0.1)  # Give time for any async cleanup

		# Verify browser is STILL alive after garbage collection
		# Verify session is still connected (checking internal state for test)
		url = await browser_session.get_current_page_url()
		assert url is not None
		if initial_pid is not None:
			# Check browser PID is still the same
			current_pid = (
				browser_session._local_browser_watchdog._subprocess.pid
				if browser_session._local_browser_watchdog and browser_session._local_browser_watchdog._subprocess
				else None
			)
			assert current_pid == initial_pid
		# Verify session is still connected
		url = await browser_session.get_current_page_url()
		assert url is not None

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
		# Verify session is still connected (checking internal state for test)
		url = await browser_session.get_current_page_url()
		assert url is not None
		if initial_pid is not None:
			# Check browser PID is still the same
			current_pid = (
				browser_session._local_browser_watchdog._subprocess.pid
				if browser_session._local_browser_watchdog and browser_session._local_browser_watchdog._subprocess
				else None
			)
			assert current_pid == initial_pid
		# Verify session is still connected
		url = await browser_session.get_current_page_url()
		assert url is not None

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
		# Check number of tabs
		tabs = await browser_session.get_tabs()
		assert len(tabs) == 2
		# Agent1 should be on the second tab (tab2)
		assert agent1.browser_session is not None
		# Check agent1 is on tab2
		url1 = await agent1.browser_session.get_current_page_url()
		assert url1 is not None
		assert '/tab2' in url1

		# Clean up agent1
		del agent1
		gc.collect()
		await asyncio.sleep(0.1)

		# Agent 2: Switch to first tab
		first_target_id = tabs[0].target_id
		agent2_actions = [
			f"""{{
				"thinking": "Switching to first tab",
				"evaluation_previous_goal": "Two tabs are open",
				"memory": "Need to switch to tab {first_target_id[-4:]}",
				"next_goal": "Switch to tab {first_target_id[-4:]}",
				"action": [
					{{"switch_tab": {{"tab_id": "{first_target_id[-4:]}"}}
				]
			}}"""
		]

		agent2 = Agent(
			task='Switch to first tab',
			llm=create_mock_llm(agent2_actions),
			browser_session=browser_session,
		)
		history2 = await agent2.run(max_steps=3)

		# Verify agent2 is on the first tab
		assert agent2.browser_session is not None
		# Check agent2 is on tab1
		url2 = await agent2.browser_session.get_current_page_url()
		assert url2 is not None
		assert '/tab1' in url2

		# Verify browser is still functional
		# Verify session is still connected (checking internal state for test)
		url = await browser_session.get_current_page_url()
		assert url is not None
		# Check number of tabs
		tabs = await browser_session.get_tabs()
		assert len(tabs) == 2

		await browser_session.kill()
