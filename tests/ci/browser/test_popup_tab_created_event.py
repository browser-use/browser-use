"""
Test that window.open() popups dispatch TabCreatedEvent so watchdogs initialize.

Before the fix, SessionManager._handle_target_attached() did not dispatch
TabCreatedEvent for externally-created popups (e.g. via window.open()).
This meant PopupsWatchdog never registered dialog handlers, AboutBlankWatchdog
never processed the tab, and viewport settings were never applied.

Tests verify that:
1. window.open() triggers TabCreatedEvent with the correct target_id
2. PopupsWatchdog registers dialog handlers for popup tabs
3. The popup navigates to the target URL (not stuck on about:blank)
4. The original page remains functional after popup creation

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


async def test_popup_navigates_to_target_url(popup_browser_session, popup_base_url):
	"""Popup created by window.open() must navigate to the target URL, not stay on about:blank."""
	session = popup_browser_session

	from browser_use.browser.events import NavigateToUrlEvent

	# Navigate to opener page
	await session.event_bus.dispatch(NavigateToUrlEvent(url=f'{popup_base_url}/opener'))
	await asyncio.sleep(1)

	# Count tabs before popup
	tabs_before = await session.get_tabs()
	count_before = len(tabs_before)

	# Trigger window.open()
	cdp_session = await session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': f"window.open('{popup_base_url}/target', '_blank')"},
		session_id=cdp_session.session_id,
	)

	# Wait for navigation to complete
	await asyncio.sleep(3)

	# Verify new tab exists
	tabs_after = await session.get_tabs()
	assert len(tabs_after) > count_before, f'Expected more tabs after window.open(), had {count_before}, now {len(tabs_after)}'

	# Find the new tab and verify it navigated to the target URL
	page_targets = session.session_manager.get_all_page_targets()
	target_urls = [t.url for t in page_targets]
	assert any('/target' in url for url in target_urls), (
		f'Popup should have navigated to /target, but tab URLs are: {target_urls}. The popup may be stuck on about:blank.'
	)


async def test_popup_watchdogs_initialize_for_window_open(popup_browser_session, popup_base_url):
	"""PopupsWatchdog must register dialog handlers for popup tabs created by window.open()."""
	session = popup_browser_session

	from browser_use.browser.events import NavigateToUrlEvent

	# Navigate to opener page
	await session.event_bus.dispatch(NavigateToUrlEvent(url=f'{popup_base_url}/opener'))
	await asyncio.sleep(1)

	# Record currently registered targets in PopupsWatchdog
	popups_watchdog = session._popups_watchdog
	registered_before = set(popups_watchdog._dialog_listeners_registered)

	# Trigger window.open()
	cdp_session = await session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': f"window.open('{popup_base_url}/target', '_blank')"},
		session_id=cdp_session.session_id,
	)

	# Wait for watchdog to process the TabCreatedEvent
	await asyncio.sleep(2)

	# Verify PopupsWatchdog registered handlers for the new popup target
	registered_after = set(popups_watchdog._dialog_listeners_registered)
	new_registrations = registered_after - registered_before
	assert len(new_registrations) >= 1, (
		f'PopupsWatchdog should have registered dialog handlers for popup tab, '
		f'but no new targets were registered. Before: {registered_before}, After: {registered_after}'
	)


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
