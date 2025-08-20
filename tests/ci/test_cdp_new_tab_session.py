"""Test CDP session handling when creating new tabs."""

import asyncio

import pytest

from browser_use.browser.events import NavigateToUrlEvent, TabCreatedEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


@pytest.fixture
async def httpserver_url(httpserver):
	"""Create a local HTTP server for testing."""
	httpserver.expect_request('/').respond_with_data(
		"""
		<html>
		<head><title>Test Page</title></head>
		<body>
			<h1>Test Page</h1>
			<p>This is a test page</p>
		</body>
		</html>
		""",
		content_type='text/html',
	)
	return httpserver.url_for('/')


@pytest.mark.skip(reason='TODO: fix')
async def test_new_tab_cdp_session_attachment(httpserver_url):
	"""Test that CDP session is properly attached when creating new tabs."""
	browser = BrowserSession(browser_profile=BrowserProfile(headless=True, viewport={'width': 800, 'height': 600}))

	tab_created_events = []

	# Track TabCreatedEvent to verify it's dispatched correctly
	browser.event_bus.on(TabCreatedEvent, lambda event: tab_created_events.append(event))

	try:
		await browser.start()

		# Navigate to initial page
		nav_event = browser.event_bus.dispatch(NavigateToUrlEvent(url=httpserver_url))
		await nav_event

		# Clear any initial tab created events
		tab_created_events.clear()

		# Now create a new tab - this should trigger the CDP error if not fixed
		new_tab_event = browser.event_bus.dispatch(NavigateToUrlEvent(url=httpserver_url, new_tab=True))
		await new_tab_event

		# Wait a bit for all events to process
		await asyncio.sleep(1)

		# Verify that TabCreatedEvent was dispatched
		assert len(tab_created_events) == 1, f'Expected 1 TabCreatedEvent, got {len(tab_created_events)}'
		assert tab_created_events[0].url == httpserver_url

		# Verify we have 2 tabs now
		tabs = await browser.get_tabs()
		assert len(tabs) == 2, f'Expected 2 tabs, got {len(tabs)}'

		# Verify the CDP session is attached to the new tab
		assert browser.agent_focus is not None
		assert browser.agent_focus.target_id is not None

		# Try to execute a CDP command on the new tab to verify it works
		cdp_session = await browser.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.title'}, session_id=cdp_session.session_id
		)
		assert result['result']['value'] == 'Test Page'

		# Get browser state to verify DOM can be built on new tab
		from browser_use.browser.events import BrowserStateRequestEvent

		state_event = browser.event_bus.dispatch(BrowserStateRequestEvent())
		state = await state_event.event_result()

		# Verify state was retrieved without errors
		assert state is not None
		assert state.dom_state is not None

	finally:
		await browser.stop()


async def test_multiple_new_tabs_cdp_session(httpserver_url):
	"""Test creating multiple new tabs in succession."""
	browser = BrowserSession(browser_profile=BrowserProfile(headless=True, viewport={'width': 800, 'height': 600}))

	try:
		await browser.start()

		# Navigate to initial page
		nav_event = browser.event_bus.dispatch(NavigateToUrlEvent(url=httpserver_url))
		await nav_event

		# Create multiple new tabs quickly
		for i in range(3):
			new_tab_event = browser.event_bus.dispatch(NavigateToUrlEvent(url=f'{httpserver_url}?tab={i}', new_tab=True))
			await new_tab_event

		# Wait for events to process
		await asyncio.sleep(1)

		# Verify we have 4 tabs total (1 initial + 3 new)
		tabs = await browser.get_tabs()
		assert len(tabs) == 4, f'Expected 4 tabs, got {len(tabs)}'

		# Verify CDP commands work on the current tab
		cdp_session = await browser.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'window.location.href'}, session_id=cdp_session.session_id
		)
		assert 'tab=2' in result['result']['value'], 'Should be on the last created tab'

	finally:
		await browser.stop()
