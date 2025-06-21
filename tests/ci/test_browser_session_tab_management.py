import asyncio
import logging

import pytest
from dotenv import load_dotenv
from pytest_httpserver import HTTPServer

load_dotenv()

from browser_use.agent.views import ActionModel
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.controller.service import Controller

# Set up test logging
logger = logging.getLogger('tab_tests')
# logger.setLevel(logging.DEBUG)


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

	# Add routes for test pages
	server.expect_request('/page1').respond_with_data(
		'<html><head><title>Test Page 1</title></head><body><h1>Test Page 1</h1></body></html>', content_type='text/html'
	)
	server.expect_request('/page2').respond_with_data(
		'<html><head><title>Test Page 2</title></head><body><h1>Test Page 2</h1></body></html>', content_type='text/html'
	)
	server.expect_request('/page3').respond_with_data(
		'<html><head><title>Test Page 3</title></head><body><h1>Test Page 3</h1></body></html>', content_type='text/html'
	)
	server.expect_request('/page4').respond_with_data(
		'<html><head><title>Test Page 4</title></head><body><h1>Test Page 4</h1></body></html>', content_type='text/html'
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session(base_url):
	"""Create and provide a BrowserSession instance with a properly initialized tab."""
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			user_data_dir=None,
			headless=True,
			keep_alive=True,
		)
	)
	await browser_session.start()

	# Create an initial tab and wait for it to load completely
	await browser_session.new_tab(f'{base_url}/page1')
	await asyncio.sleep(1)  # Wait for the tab to fully initialize

	# Verify that agent_current_page and human_current_page are properly set
	assert browser_session.agent_current_page is not None
	assert browser_session.human_current_page is not None
	assert base_url in browser_session.agent_current_page.url

	yield browser_session

	await browser_session.kill()

	# Give playwright time to clean up
	await asyncio.sleep(0.1)


@pytest.fixture(scope='module')
def controller():
	"""Create and provide a Controller instance."""
	return Controller()


class TestTabManagement:
	"""Tests for the tab management system with separate agent_current_page and human_current_page references."""

	# Helper methods

	async def _execute_action(self, controller, browser_session: BrowserSession, action_data):
		"""Generic helper to execute any action via the controller."""
		# Dynamically create an appropriate ActionModel class
		action_type = list(action_data.keys())[0]
		action_value = action_data[action_type]

		# Create the ActionModel with the single action field
		class DynamicActionModel(ActionModel):
			pass

		# Dynamically add the field with the right type annotation
		setattr(DynamicActionModel, action_type, type(action_value) | None)

		# Execute the action
		result = await controller.act(DynamicActionModel(**action_data), browser_session)

		# Give the browser a moment to process the action
		await asyncio.sleep(0.5)

		return result

	async def _reset_tab_state(self, browser_session: BrowserSession, base_url: str):
		browser_session.human_current_page = None
		browser_session.agent_current_page = None

		# close all existing tabs
		if browser_session.browser_context:
			for page in browser_session.browser_context.pages:  # type: ignore
				await page.close()

		await asyncio.sleep(0.5)

		# open one new tab and set it as the human_current_page & agent_current_page
		initial_tab = await browser_session.get_current_page()

		assert initial_tab is not None
		assert browser_session.human_current_page is not None
		assert browser_session.agent_current_page is not None
		assert browser_session.human_current_page.url == initial_tab.url
		assert browser_session.agent_current_page.url == initial_tab.url
		return initial_tab

	async def _simulate_human_tab_change(self, page, browser_session: BrowserSession):
		"""Simulate a user changing tabs by properly triggering events with Playwright."""

		# logger.debug(
		# f'BEFORE: agent_tab={browser_session.agent_current_page.url if browser_session.agent_current_page else "None"}, '
		# f'human_current_page={browser_session.human_current_page.url if browser_session.human_current_page else "None"}'
		# )
		# logger.debug(f'Simulating user changing to -> {page.url}')

		# First bring the page to front - this is the physical action a user would take
		await page.bring_to_front()

		# To simulate a user switching tabs, we need to trigger the right events
		# Use Playwright's dispatch_event method to properly trigger events from outside

		await page.dispatch_event('body', 'focus')
		# await page.evaluate("""() => window.dispatchEvent(new Event('focus'))""")
		# await page.evaluate(
		# 	"""() => document.dispatchEvent(new Event('pointermove', { bubbles: true, cancelable: false, clientX: 0, clientY: 0 }))"""
		# )
		# await page.evaluate(
		# 	"() => document.dispatchEvent(new Event('deviceorientation', { bubbles: true, cancelable: false, alpha: 0, beta: 0, gamma: 0 }))"
		# )
		# await page.evaluate(
		# 	"""() => document.dispatchEvent(new Event('visibilitychange', { bubbles: true, cancelable: false }))"""
		# )
		# logger.debug('Dispatched window.focus event')

		# cheat for now, because playwright really messes with foreground tab detection
		# TODO: fix this properly by triggering the right events and detecting them in playwright
		if page.url == 'about:blank':
			raise Exception(
				'Cannot simulate tab change on about:blank because cannot execute JS to fire focus event on about:blank'
			)
		await page.evaluate("""async () => {
			return await window._BrowserUseonTabVisibilityChange({ bubbles: true, cancelable: false });
		}""")

		# Give the event handlers time to process
		await asyncio.sleep(0.5)

		# logger.debug(
		# 	f'AFTER: agent_tab URL={browser_session.agent_current_page.url if browser_session.agent_current_page else "None"}, '
		# 	f'human_current_page URL={browser_session.human_current_page.url if browser_session.human_current_page else "None"}'
		# )

	# Tab management tests

	async def test_initial_values(self, browser_session, base_url):
		"""Test that open_tab correctly updates both tab references."""

		await self._reset_tab_state(browser_session, base_url)

		initial_tab = await browser_session.get_current_page()
		assert initial_tab.url == 'about:blank'
		assert browser_session.human_current_page == initial_tab
		assert browser_session.agent_current_page == initial_tab

		for page in browser_session.browser_context.pages:
			await page.close()

		# should never be none even after all pages are closed
		current_tab = await browser_session.get_current_page()
		assert current_tab is not None
		assert current_tab.url == 'about:blank'

	async def test_agent_changes_tab(self, browser_session, base_url):
		"""Test that agent_current_page changes and human_current_page remains the same when a new tab is opened."""

		initial_tab = await self._reset_tab_state(browser_session, base_url)
		await initial_tab.goto(f'{base_url}/page1')
		await self._simulate_human_tab_change(initial_tab, browser_session)
		assert initial_tab.url == f'{base_url}/page1'
		initial_tab_count = len(browser_session.tabs)
		assert initial_tab_count == 1

		# test opening a new tab
		new_tab = await browser_session.create_new_tab(f'{base_url}/page2')
		new_tab_count = len(browser_session.browser_context.pages)
		assert (
			new_tab_count == len(browser_session.tabs) == 2
		)  # get_current_page/create_new_tab should have auto-closed unused about:blank pages

		# test agent open new tab updates agent focus + doesn't steal human focus
		assert browser_session.agent_current_page.url == new_tab.url == f'{base_url}/page2'
		assert browser_session.human_current_page.url == initial_tab.url == f'{base_url}/page1'

		# test agent navigation updates agent focus +doesn't steal human focus
		await browser_session.navigate(f'{base_url}/page3')
		assert browser_session.agent_current_page.url == f'{base_url}/page3'  # agent should now be on the new tab
		assert (
			browser_session.human_current_page.url == initial_tab.url == f'{base_url}/page1'
		)  # human should still be on the very first tab

	async def test_human_changes_tab(self, browser_session, base_url):
		"""Test that human_current_page changes and agent_current_page remains the same when a new tab is opened."""

		initial_tab = await self._reset_tab_state(browser_session, base_url)
		assert initial_tab.url == 'about:blank'

		# assert human opening new tab updates human focus + doesn't steal agent focus
		new_human_tab = await browser_session.browser_context.new_page()
		await new_human_tab.goto(f'{base_url}/page2')
		await self._simulate_human_tab_change(new_human_tab, browser_session)
		current_agent_page = await browser_session.get_current_page()
		assert current_agent_page.url == initial_tab.url == 'about:blank'
		assert browser_session.human_current_page.url == new_human_tab.url == f'{base_url}/page2'

		# test human navigating to new URL updates human focus + doesn't steal agent focus
		await new_human_tab.goto(f'{base_url}/page3')
		await self._simulate_human_tab_change(new_human_tab, browser_session)
		current_agent_page = await browser_session.get_current_page()
		assert current_agent_page.url == initial_tab.url == 'about:blank'
		assert browser_session.human_current_page.url == new_human_tab.url == f'{base_url}/page3'

	async def test_switch_tab(self, browser_session, base_url):
		"""Test that switch_tab updates both tab references."""

		# open a new tab for the human + agent to start on
		first_tab = await self._reset_tab_state(browser_session, base_url)
		await browser_session.navigate(f'{base_url}/page1')
		await self._simulate_human_tab_change(first_tab, browser_session)
		assert first_tab.url == f'{base_url}/page1'

		# open a new tab that the agent will switch to automatically
		second_tab = await browser_session.create_new_tab(f'{base_url}/page2')
		current_tab = await browser_session.get_current_page()

		# assert agent focus is on new tab and human focus is on first tab
		assert current_tab.url == second_tab.url == f'{base_url}/page2' == browser_session.agent_current_page.url
		assert browser_session.human_current_page.url == first_tab.url == f'{base_url}/page1'

		# Switch agent back to the first tab
		await browser_session.switch_tab(0)
		await asyncio.sleep(0.5)

		# assert agent focus is on first tab and human focus is also first tab
		current_tab = await browser_session.get_current_page()
		assert current_tab.url == first_tab.url == f'{base_url}/page1' == browser_session.agent_current_page.url
		assert browser_session.human_current_page.url == first_tab.url == f'{base_url}/page1'

		# round-trip, switch agent back to second tab
		await browser_session.switch_tab(1)
		await asyncio.sleep(0.5)

		# assert agent focus is back on second tab and human focus is still on first tab
		current_tab = await browser_session.get_current_page()
		assert current_tab.url == second_tab.url == f'{base_url}/page2' == browser_session.agent_current_page.url
		assert browser_session.human_current_page.url == first_tab.url == f'{base_url}/page1'

	async def test_close_tab(self, browser_session, base_url):
		"""Test that closing a tab updates references correctly."""

		initial_tab = await self._reset_tab_state(browser_session, base_url)
		await browser_session.navigate(f'{base_url}/page1')
		assert initial_tab.url == f'{base_url}/page1'

		# Create two tabs with different URLs
		second_tab = await browser_session.create_new_tab(f'{base_url}/page2')

		# Verify the second tab is now active
		current_page = await browser_session.get_current_page()
		assert current_page.url == second_tab.url == f'{base_url}/page2'

		# Close the second tab
		await browser_session.close_tab()
		await asyncio.sleep(0.5)

		# Both references should be auto-updated to the first available tab
		assert browser_session.human_current_page.url == initial_tab.url == f'{base_url}/page1'
		assert browser_session.agent_current_page.url == initial_tab.url == f'{base_url}/page1'
		assert not browser_session.human_current_page.is_closed()
		assert not browser_session.agent_current_page.is_closed()

		# close the only remaining tab
		await browser_session.close_tab()
		await asyncio.sleep(0.5)

		# close_tab should have called get_current_page, which creates a new about:blank tab if none are left
		assert browser_session.human_current_page.url == 'about:blank'
		assert browser_session.agent_current_page.url == 'about:blank'

	async def test_browser_context_state_after_error(self, browser_session):
		"""Test browser context state remains consistent after errors"""
		# logger.info('Testing browser context state after error')

		await browser_session.start()

		# Force an error by closing context and trying to use it
		# Set browser_context to None to simulate partial cleanup
		await browser_session.browser_context.close()
		original_context = browser_session.browser_context
		browser_session.browser_context = None

		# This should trigger reinitialization
		page = await browser_session.get_current_page()

		# Verify state is consistent
		assert page is not None
		assert browser_session.browser_context is not None
		assert browser_session.browser_context != original_context
		assert browser_session.initialized is True
		assert browser_session.is_connected() is True

	async def test_concurrent_context_access_during_closure(self, browser_session):
		"""Test concurrent access to browser context during closure"""
		# logger.info('Testing concurrent context access during closure')

		await browser_session.start()
		assert browser_session.is_connected() is True

		# Create a barrier to synchronize operations
		barrier = asyncio.Barrier(3)

		async def close_context():
			await barrier.wait()
			await browser_session.browser_context.browser.close()
			assert browser_session.is_connected() is False
			return 'closed'

		async def access_pages():
			await barrier.wait()
			try:
				pages = await browser_session.get_tabs_info()
				return f'pages: {len(pages)}'
			except Exception as e:
				return f'error: {type(e).__name__}'

		async def check_connection():
			await barrier.wait()
			await asyncio.sleep(0.01)  # Small delay to let close start
			connected = browser_session.is_connected()
			return f'connected: {connected}'

		# Run all operations concurrently
		results = await asyncio.gather(close_context(), access_pages(), check_connection(), return_exceptions=True)

		# All operations should complete without crashes
		assert all(not isinstance(r, Exception) for r in results)
		assert 'closed' in results

		await browser_session.kill()
		await asyncio.sleep(0.5)
