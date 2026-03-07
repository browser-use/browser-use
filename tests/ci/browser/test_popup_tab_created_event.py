"""
Test that window.open() popups dispatch TabCreatedEvent so watchdogs initialize.

Before the fix, SessionManager._handle_target_attached() did not dispatch
TabCreatedEvent for externally-created popups (e.g. via window.open()).
This meant PopupsWatchdog never registered dialog handlers, AboutBlankWatchdog
never processed the tab, and viewport settings were never applied.

Tests verify that:
1. window.open() triggers TabCreatedEvent with a valid target_id
2. The TabCreatedEvent carries a usable URL (not empty string)
3. The original page remains functional after popup creation

Usage:
	uv run pytest tests/ci/browser/test_popup_tab_created_event.py -v -s
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.events import TabCreatedEvent
from browser_use.browser.profile import BrowserProfile


@pytest.fixture(scope='session')
def popup_http_server():
	"""Test HTTP server with pages that trigger window.open()."""
	server = HTTPServer()
	server.start()

	# Main page with a button that calls window.open()
	server.expect_request('/opener').respond_with_data(
		"""<!DOCTYPE html>
		<html>
		<head><title>Opener Page</title></head>
		<body>
			<h1>Opener</h1>
			<button id="open-popup" onclick="window.open('/target', '_blank')">Open Popup</button>
			<p id="status">ready</p>
		</body>
		</html>""",
		content_type='text/html',
	)

	# Target page that popups navigate to
	server.expect_request('/target').respond_with_data(
		"""<!DOCTYPE html>
		<html>
		<head><title>Target Page</title></head>
		<body><h1>Target Reached</h1></body>
		</html>""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def popup_base_url(popup_http_server):
	return f'http://{popup_http_server.host}:{popup_http_server.port}'


@pytest.fixture(scope='function')
async def popup_browser_session():
	"""Browser session for popup tests."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			enable_default_extensions=False,
		)
	)
	await session.start()
	yield session
	await session.kill()


async def test_window_open_dispatches_tab_created_event(popup_browser_session, popup_base_url):
	"""window.open() must dispatch TabCreatedEvent so watchdogs can initialize."""
	session = popup_browser_session

	# Collect TabCreatedEvents
	captured_events: list[TabCreatedEvent] = []

	async def on_tab_created(event: TabCreatedEvent):
		captured_events.append(event)

	session.event_bus.on(TabCreatedEvent, on_tab_created)

	# Navigate to opener page
	from browser_use.browser.events import NavigateToUrlEvent

	await session.event_bus.dispatch(NavigateToUrlEvent(url=f'{popup_base_url}/opener'))
	await asyncio.sleep(1)

	initial_event_count = len(captured_events)

	# Trigger window.open() via JavaScript
	cdp_session = await session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "window.open('/target', '_blank')"},
		session_id=cdp_session.session_id,
	)

	# Wait for the popup to be processed
	await asyncio.sleep(2)

	# Verify a new TabCreatedEvent was dispatched for the popup
	new_events = captured_events[initial_event_count:]
	assert len(new_events) >= 1, (
		f'Expected at least 1 TabCreatedEvent after window.open(), got {len(new_events)}. '
		'SessionManager._handle_target_attached must dispatch TabCreatedEvent for popup tabs.'
	)

	# The popup event should have a valid target_id
	popup_event = new_events[0]
	assert popup_event.target_id, 'TabCreatedEvent for popup must have a target_id'


async def test_tab_created_event_has_valid_url(popup_browser_session, popup_base_url):
	"""TabCreatedEvent URL must never be empty — SecurityWatchdog would reject it."""
	session = popup_browser_session

	captured_events: list[TabCreatedEvent] = []

	async def on_tab_created(event: TabCreatedEvent):
		captured_events.append(event)

	session.event_bus.on(TabCreatedEvent, on_tab_created)

	from browser_use.browser.events import NavigateToUrlEvent

	await session.event_bus.dispatch(NavigateToUrlEvent(url=f'{popup_base_url}/opener'))
	await asyncio.sleep(1)

	initial_event_count = len(captured_events)

	# Trigger window.open() via JavaScript
	cdp_session = await session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': f"window.open('{popup_base_url}/target', '_blank')"},
		session_id=cdp_session.session_id,
	)

	await asyncio.sleep(2)

	new_events = captured_events[initial_event_count:]
	assert len(new_events) >= 1, 'Expected TabCreatedEvent after window.open()'

	# URL must be non-empty (empty string causes SecurityWatchdog to close the tab)
	for event in new_events:
		assert event.url, f'TabCreatedEvent url must not be empty, got: {event.url!r}'


async def test_original_page_functional_after_popup(popup_browser_session, popup_base_url):
	"""The original page must remain functional after window.open() creates a popup."""
	session = popup_browser_session

	from browser_use.browser.events import NavigateToUrlEvent

	# Navigate to opener page
	await session.event_bus.dispatch(NavigateToUrlEvent(url=f'{popup_base_url}/opener'))
	await asyncio.sleep(1)

	# Trigger window.open()
	cdp_session = await session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': f"window.open('{popup_base_url}/target', '_blank')"},
		session_id=cdp_session.session_id,
	)

	await asyncio.sleep(2)

	# Verify the original page is still responsive by executing JS on it
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('status').textContent"},
		session_id=cdp_session.session_id,
	)

	assert result.get('result', {}).get('value') == 'ready', (
		f'Original page should still be functional after popup, but status element returned: {result}'
	)
