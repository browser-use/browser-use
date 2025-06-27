"""
Test that sequential agents can properly reuse the same BrowserSession without
it being closed prematurely due to garbage collection or page handle issues.
"""

import asyncio
import gc

from browser_use import Agent, BrowserProfile, BrowserSession
from tests.ci.conftest import create_mock_llm


class TestSequentialAgentsReuse:
	"""Test that sequential agents can properly reuse the same BrowserSession"""

	async def test_sequential_agents_share_browser_session(self, httpserver):
		"""Test that multiple agents can reuse the same browser session without it being closed"""
		# Set up test HTML pages
		httpserver.expect_request('/page1').respond_with_data(
			'<html><body><h1>Page 1</h1><a href="/page2">Go to Page 2</a></body></html>'
		)
		httpserver.expect_request('/page2').respond_with_data(
			'<html><body><h1>Page 2</h1><a href="/page3">Go to Page 3</a></body></html>'
		)
		httpserver.expect_request('/page3').respond_with_data(
			'<html><body><h1>Page 3</h1><div id="result">Success!</div></body></html>'
		)

		# Create a browser session with keep_alive=True
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				keep_alive=True,
				headless=True,
				user_data_dir=None,  # Use temporary directory
			)
		)
		await browser_session.start()

		# Agent 1: Navigate to page 1 and open a new tab
		agent1_actions = [
			f"""{{
				"thinking": "Navigating to page 1 and opening page 2 in new tab",
				"evaluation_previous_goal": "Starting task",
				"memory": "Need to navigate to page 1 and open new tab",
				"next_goal": "Navigate to page 1 and open page 2 in new tab",
				"action": [
					{{"go_to_url": {{"url": "{httpserver.url_for('/page1')}"}}}},
					{{"open_tab": {{"url": "{httpserver.url_for('/page2')}"}}}}
				]
			}}"""
		]

		agent1 = Agent(
			task='Navigate to page 1 and open page 2 in a new tab',
			llm=create_mock_llm(agent1_actions),
			browser_session=browser_session,
		)
		history1 = await agent1.run(max_steps=2)
		assert len(history1.history) >= 1
		assert history1.history[-1].state.url == httpserver.url_for('/page2')

		# Verify browser session is still alive
		assert browser_session.initialized
		# browser_pid can be None in CI environments - check browser context instead
		assert browser_session.browser_context is not None
		assert len(browser_session.tabs) == 2  # Two tabs should be open

		# Agent 2: Switch to tab 0 and click the link to navigate to page2
		agent2_actions = [
			"""{
				"thinking": "Switching to first tab",
				"evaluation_previous_goal": "Previous agent opened two tabs successfully",
				"memory": "Two tabs are open, need to switch to first one",
				"next_goal": "Switch to tab 0",
				"action": [
					{
						"switch_tab": {
							"page_id": 0
						}
					}
				]
			}""",
			"""{
				"thinking": "Taking screenshot to refresh page state after tab switch",
				"evaluation_previous_goal": "Switched to tab 0 successfully",
				"memory": "Now on tab 0, need to see what's on the page",
				"next_goal": "Take screenshot to refresh page state",
				"action": [
					{
						"screenshot": {}
					}
				]
			}""",
			f"""{{
				"thinking": "Navigating directly to page 2",
				"evaluation_previous_goal": "Can see page 1 with link",
				"memory": "Page has a link to page 2, will navigate directly",
				"next_goal": "Navigate to page 2",
				"action": [
					{{
						"go_to_url": {{
							"url": "{httpserver.url_for('/page2')}"
						}}
					}}
				]
			}}""",
			"""{
				"thinking": "Taking screenshot to confirm navigation",
				"evaluation_previous_goal": "Navigated to page 2",
				"memory": "Should now be on page 2",
				"next_goal": "Confirm we are on page 2",
				"action": [
					{
						"screenshot": {}
					}
				]
			}""",
		]

		agent2 = Agent(
			task='Switch to the first tab and click the link',
			llm=create_mock_llm(agent2_actions),
			browser_session=browser_session,
		)
		history2 = await agent2.run(max_steps=len(agent2_actions))
		assert len(history2.history) >= 1
		# Check the URLs in the history to find the successful navigation
		urls = [h.state.url for h in history2.history if h.state and h.state.url]
		assert httpserver.url_for('/page2') in urls, f'Expected {httpserver.url_for("/page2")} in URLs: {urls}'

		# Verify browser session is still alive after second agent
		assert browser_session.initialized
		assert browser_session.browser_context is not None

		# Agent 3: Navigate to page 3
		agent3_actions = [
			f"""{{
				"thinking": "Navigating to page 3",
				"evaluation_previous_goal": "Now on page 2",
				"memory": "Need to go to page 3",
				"next_goal": "Navigate to page 3",
				"action": [
					{{
						"go_to_url": {{
							"url": "{httpserver.url_for('/page3')}"
						}}
					}}
				]
			}}""",
			"""{
				"thinking": "Confirming navigation",
				"evaluation_previous_goal": "Navigated to page 3",
				"memory": "Should now be on page 3",
				"next_goal": "Confirm on page 3",
				"action": [
					{
						"screenshot": {}
					}
				]
			}""",
		]

		agent3 = Agent(
			task='Click link to go to page 3',
			llm=create_mock_llm(agent3_actions),
			browser_session=browser_session,
		)
		history3 = await agent3.run(max_steps=2)
		assert len(history3.history) >= 1
		# Check that page3 was visited
		urls3 = [h.state.url for h in history3.history if h.state and h.state.url]
		assert httpserver.url_for('/page3') in urls3, f'Expected {httpserver.url_for("/page3")} in URLs: {urls3}'

		# Agent 4: Take a screenshot to confirm we're on page 3
		agent4_actions = [
			"""{
				"thinking": "Taking screenshot on page 3",
				"evaluation_previous_goal": "Successfully navigated to page 3",
				"memory": "On page 3, need to take screenshot",
				"next_goal": "Take screenshot of page 3",
				"action": [
					{"screenshot": {}}
				]
			}"""
		]

		agent4 = Agent(
			task='Take screenshot on page 3',
			llm=create_mock_llm(agent4_actions),
			browser_session=browser_session,
		)
		history4 = await agent4.run(max_steps=2)
		assert len(history4.history) >= 1

		# Verify that agent 4 was on page 3
		urls4 = [h.state.url for h in history4.history if h.state and h.state.url]
		assert httpserver.url_for('/page3') in urls4, f'Expected {httpserver.url_for("/page3")} in URLs: {urls4}'

		# Clean up
		await browser_session.stop()

	async def test_sequential_agents_share_browser_state(self, httpserver):
		"""Test that sequential agents properly share browser session state including current page"""
		# Set up test pages
		httpserver.expect_request('/a').respond_with_data('<html><body><h1>Page A</h1></body></html>')
		httpserver.expect_request('/b').respond_with_data('<html><body><h1>Page B</h1></body></html>')

		# Create shared browser session
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				keep_alive=True,
				headless=True,
				user_data_dir=None,  # Use temporary directory
			)
		)
		await browser_session.start()

		# Agent 1 opens two tabs
		agent1_actions = [
			f"""{{
				"thinking": "Opening two tabs",
				"evaluation_previous_goal": "Starting task",
				"memory": "Need to open page A and page B",
				"next_goal": "Open two tabs with different pages",
				"action": [
					{{"go_to_url": {{"url": "{httpserver.url_for('/a')}"}}}},
					{{"open_tab": {{"url": "{httpserver.url_for('/b')}"}}}}
				]
			}}"""
		]

		agent1 = Agent(
			task='Open two tabs',
			llm=create_mock_llm(agent1_actions),
			browser_session=browser_session,
		)
		await agent1.run(max_steps=2)

		# Verify agent1's view - should be on tab 1 (page B)
		assert agent1.browser_session
		assert agent1.browser_session.agent_current_page is not None
		assert '/b' in agent1.browser_session.agent_current_page.url

		# Agent 2 switches back to first tab
		agent2_actions = [
			"""{
				"thinking": "Switching to first tab",
				"evaluation_previous_goal": "Two tabs are open",
				"memory": "Need to switch to tab 0",
				"next_goal": "Switch to first tab",
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
		await agent2.run(max_steps=2)

		# Verify agent2's view - should be on tab 0 (page A)
		assert agent2.browser_session
		assert agent2.browser_session.agent_current_page is not None
		assert '/a' in agent2.browser_session.agent_current_page.url

		# When agents share a browser session sequentially, the current page
		# is shared state - agent2's tab switch affects the session's current page
		# This is expected behavior for sequential session sharing

		await browser_session.stop()

	async def test_garbage_collection_doesnt_close_browser(self, httpserver):
		"""Test that browser doesn't close when agent is garbage collected"""
		httpserver.expect_request('/test').respond_with_data('<html><body>Test</body></html>')

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				keep_alive=True,
				headless=True,
				user_data_dir=None,  # Use temporary directory
			)
		)
		await browser_session.start()

		# Store initial browser process ID if available
		initial_browser_pid = browser_session.browser_pid

		# Create and run first agent in a scope that will be garbage collected
		async def run_agent1():
			agent1_actions = [
				f'''{{
					"thinking": "Navigating to test page",
					"evaluation_previous_goal": "Starting task",
					"memory": "Need to go to test page",
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

			agent1 = Agent(
				task='Navigate to test page',
				llm=create_mock_llm(agent1_actions),
				browser_session=browser_session,
			)
			await agent1.run(max_steps=2)
			# agent1 goes out of scope here and should be garbage collected

		await run_agent1()

		# Force garbage collection
		gc.collect()
		await asyncio.sleep(0.1)  # Give time for any async cleanup

		# Verify browser is still alive
		assert browser_session.initialized
		assert browser_session.browser_context is not None
		# Only check browser_pid if it was available initially
		if initial_browser_pid is not None:
			assert browser_session.browser_pid == initial_browser_pid  # Same browser process

		# Create second agent - should work without issues
		agent2_actions = [
			"""{
				"thinking": "Taking screenshot of current page",
				"evaluation_previous_goal": "On test page",
				"memory": "Need to take screenshot",
				"next_goal": "Take screenshot",
				"action": [
					{
						"screenshot": {}
					}
				]
			}"""
		]

		agent2 = Agent(
			task='Take screenshot',
			llm=create_mock_llm(agent2_actions),
			browser_session=browser_session,
		)
		history = await agent2.run(max_steps=2)
		assert len(history.history) >= 1

		# Verify screenshot was taken successfully
		screenshot_taken = False
		for step in history.history:
			for result in step.result:
				if hasattr(result, 'screenshot'):
					screenshot_taken = True
					break
		assert screenshot_taken, 'Screenshot was not taken successfully'

		await browser_session.stop()

	async def test_multiple_tabs_with_sequential_agents(self, httpserver):
		"""Test that opening multiple tabs doesn't break page handles when switching agents"""
		# Set up test pages
		for i in range(5):
			httpserver.expect_request(f'/page{i}').respond_with_data(
				f'<html><body><h1>Page {i}</h1><div id="content">Content {i}</div></body></html>'
			)

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				keep_alive=True,
				headless=True,
				user_data_dir=None,  # Use temporary directory
			)
		)
		await browser_session.start()

		# Agent 1: Open 4 tabs
		tab_actions = []
		for i in range(4):
			url = httpserver.url_for(f'/page{i}')
			if i == 0:
				tab_actions.append(f'{{"go_to_url": {{"url": "{url}"}}}}')
			else:
				tab_actions.append(f'{{"open_tab": {{"url": "{url}"}}}}')

		agent1_actions = [
			f"""{{
				"thinking": "Opening multiple tabs",
				"evaluation_previous_goal": "Starting task",
				"memory": "Need to open 4 tabs",
				"next_goal": "Open 4 different pages in tabs",
				"action": [{', '.join(tab_actions)}]
			}}"""
		]

		agent1 = Agent(
			task='Open 4 tabs with different pages',
			llm=create_mock_llm(agent1_actions),
			browser_session=browser_session,
		)
		await agent1.run(max_steps=2)

		# Verify 4 tabs are open
		assert len(browser_session.tabs) == 4

		# Agent 2: Switch between tabs and take screenshots
		agent2_actions = []
		for i in [2, 0, 3, 1]:  # Random order
			agent2_actions.append(
				f"""{{
					"thinking": "Switching to tab {i} and taking screenshot",
					"evaluation_previous_goal": "Ready to switch tabs",
					"memory": "Multiple tabs are open",
					"next_goal": "Switch to tab {i} and screenshot",
					"action": [
						{{"switch_tab": {{"page_id": {i}}}}},
						{{"screenshot": {{}}}}
					]
				}}"""
			)

		agent2 = Agent(
			task='Switch between tabs and take screenshots',
			llm=create_mock_llm(agent2_actions),
			browser_session=browser_session,
		)
		history2 = await agent2.run(max_steps=len(agent2_actions) + 1)

		# Verify we successfully switched tabs and took screenshots
		assert len(history2.history) >= len(agent2_actions)

		# Verify browser is still functional
		assert browser_session.initialized
		assert browser_session.browser_context is not None
		assert len(browser_session.tabs) == 4

		await browser_session.stop()
