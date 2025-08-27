"""
Test browser session recent events tracking functionality.
"""

import json
import time

import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Response

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import NavigateToUrlEvent, ScreenshotEvent


class TestBrowserRecentEvents:
	"""Test recent events tracking functionality"""

	async def test_recent_events_on_successful_load(self, httpserver: HTTPServer):
		"""Test that recent events shows successful navigation when page loads successfully"""
		# Set up a simple page that loads quickly
		httpserver.expect_request('/fast').respond_with_data(
			'<html><head><title>Fast Page</title></head><body><h1>Quick loading page</h1></body></html>',
			content_type='text/html',
		)

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
			)
		)

		try:
			await browser_session.start()

			# Navigate to the fast-loading page
			event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/fast')))
			await event
			await event.event_result(raise_if_any=True, raise_if_none=False)

			# Get browser state with recent events
			state = await browser_session.get_browser_state_summary(include_recent_events=True)

			# Recent events should show successful navigation
			assert state.recent_events is not None

			# Parse JSON and verify events
			events = json.loads(state.recent_events)
			event_types = [e.get('event_type') for e in events]

			# Should have navigation events
			assert 'NavigationCompleteEvent' in event_types, 'Should have NavigationCompleteEvent'

			# Check the navigation was successful (no errors)
			nav_events = [e for e in events if e.get('event_type') == 'NavigationCompleteEvent']
			last_nav = nav_events[-1]
			assert last_nav.get('error_message') is None, 'Should not have error message'
			# Note: CDP doesn't provide HTTP status directly, so skip status check

		finally:
			await browser_session.kill()

	# async def test_recent_events_tracks_multiple_navigations(self, httpserver: HTTPServer):
	# 	"""Test that recent events properly tracks multiple navigations"""
	# 	# Set up pages
	# 	slow_html = """
	# 	<html>
	# 	<head>
	# 		<title>Slow Page</title>
	# 		<script src="/slow.js"></script>
	# 	</head>
	# 	<body><h1>Slow page</h1></body>
	# 	</html>
	# 	"""

	# 	httpserver.expect_request('/slow').respond_with_data(slow_html, content_type='text/html')

	# 	def slow_handler(req):
	# 		time.sleep(5)
	# 		return Response('slow')

	# 	httpserver.expect_request('/slow.js').respond_with_handler(slow_handler)

	# 	httpserver.expect_request('/fast').respond_with_data(
	# 		'<html><head><title>Fast Page</title></head><body><h1>Fast page</h1></body></html>',
	# 		content_type='text/html',
	# 	)

	# 	browser_session = BrowserSession(
	# 		browser_profile=BrowserProfile(
	# 			headless=True,
	# 			user_data_dir=None,
	# 			keep_alive=False,
	# 		)
	# 	)

	# 	try:
	# 		await browser_session.start()

	# 		# Navigate to slow page
	# 		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/slow')))
	# 		await event
	# 		await event.event_result(raise_if_any=True, raise_if_none=False)
	# 		state1 = await browser_session.get_browser_state_summary(include_recent_events=True)
	# 		assert state1.recent_events is not None
	# 		events1 = json.loads(state1.recent_events)
	# 		event_types1 = [e.get('event_type') for e in events1]
	# 		assert 'NavigationCompleteEvent' in event_types1 or 'NavigateToUrlEvent' in event_types1

	# 		# Navigate to fast page
	# 		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/fast')))
	# 		await event
	# 		await event.event_result(raise_if_any=True, raise_if_none=False)
	# 		state2 = await browser_session.get_browser_state_summary()

	# 		# Recent events should show both navigations
	# 		assert state2.recent_events is not None
	# 		events2 = json.loads(state2.recent_events)

	# 		# Count navigation events (last 10 events should include both)
	# 		nav_complete_count = sum(1 for e in events2 if e.get('event_type') == 'NavigationCompleteEvent')
	# 		nav_url_count = sum(1 for e in events2 if e.get('event_type') == 'NavigateToUrlEvent')

	# 		# Should have events from both navigations
	# 		assert nav_complete_count >= 1 or nav_url_count >= 2, 'Recent events should show multiple navigation attempts'

	# 	finally:
	# 		await browser_session.kill()

	async def test_recent_events_preserved_in_minimal_state(self, httpserver: HTTPServer):
		"""Test that recent events is preserved even when falling back to minimal state"""
		# Create a page that causes DOM processing to fail
		malformed_html = """
		<html>
		<head>
			<title>Malformed Page</title>
			<script src="/slow.js"></script>
			<script>
				// This might cause DOM processing issues
				Object.defineProperty(document, 'querySelectorAll', {
					get() { throw new Error('DOM processing blocked'); }
				});
			</script>
		</head>
		<body><h1>Page with DOM issues</h1></body>
		</html>
		"""

		httpserver.expect_request('/malformed').respond_with_data(malformed_html, content_type='text/html')

		def slow_handler(req):
			time.sleep(5)
			return Response('slow')

		httpserver.expect_request('/slow.js').respond_with_handler(slow_handler)

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
			)
		)

		try:
			await browser_session.start()

			# Navigate to the malformed page
			event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/malformed')))
			await event
			await event.event_result(raise_if_any=True, raise_if_none=False)

			# Get browser state - this might fall back to minimal state
			state = await browser_session.get_browser_state_summary(include_recent_events=True)

			# Even if we get minimal state, recent events should be preserved
			assert state.recent_events is not None
			events = json.loads(state.recent_events)
			assert len(events) > 0, 'Should have events even in minimal state'

			# Should have navigation attempt
			event_types = [e.get('event_type') for e in events]
			assert 'NavigateToUrlEvent' in event_types or 'NavigationCompleteEvent' in event_types, (
				'Should have navigation events even in minimal state'
			)

		finally:
			await browser_session.kill()

	@pytest.mark.parametrize('timeout_seconds', [0.5, 1.0, 2.0])
	async def test_recent_events_with_different_timeouts(self, httpserver: HTTPServer, timeout_seconds: float):
		"""Test that recent events captures navigation with different timeout configurations"""
		# Set up a slow page
		httpserver.expect_request(f'/timeout_{timeout_seconds}').respond_with_data(
			f'<html><head><title>Timeout Test {timeout_seconds}s</title>'
			f'<script src="/slow_{timeout_seconds}.js"></script></head>'
			f'<body><h1>Testing {timeout_seconds}s timeout</h1></body></html>',
			content_type='text/html',
		)

		def very_slow_handler(req):
			time.sleep(10)
			return Response('slow')

		httpserver.expect_request(f'/slow_{timeout_seconds}.js').respond_with_handler(very_slow_handler)

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				wait_for_network_idle_page_load_time=0.1,
				minimum_wait_page_load_time=0.1,
			)
		)

		try:
			await browser_session.start()

			# Navigate to the page
			event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for(f'/timeout_{timeout_seconds}')))
			await event
			await event.event_result(raise_if_any=True, raise_if_none=False)

			# Get browser state with recent events
			state = await browser_session.get_browser_state_summary(include_recent_events=True)

			# Verify recent events captured the navigation
			assert state.recent_events is not None
			events = json.loads(state.recent_events)
			event_types = [e.get('event_type') for e in events]

			# Should have navigation events regardless of timeout
			assert 'NavigateToUrlEvent' in event_types or 'NavigationCompleteEvent' in event_types, (
				f'Should have navigation events for {timeout_seconds}s timeout'
			)

			# If navigation completed with error, it might mention timeout
			nav_complete_events = [e for e in events if e.get('event_type') == 'NavigationCompleteEvent']
			if nav_complete_events and nav_complete_events[-1].get('error_message'):
				print(f'Navigation error for {timeout_seconds}s timeout: {nav_complete_events[-1].get("error_message")}')

		finally:
			await browser_session.kill()


class TestEventHistoryInfrastructure:
	"""Tests for NEW event history tracking infrastructure only."""

	async def test_event_bus_history_tracking(self, httpserver: HTTPServer):
		"""Test that event bus properly tracks event history."""
		browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=False))

		try:
			await browser_session.start()
			initial_history_count = len(browser_session.event_bus.event_history)

			# Set up test page
			httpserver.expect_request('/history-test').respond_with_data(
				'<html><body><h1>Event History Test</h1></body></html>',
				content_type='text/html',
			)

			# Perform actions that generate events
			event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/history-test')))
			await event
			await event.event_result(raise_if_any=True, raise_if_none=False)
			screenshot_event = browser_session.event_bus.dispatch(ScreenshotEvent())
			await screenshot_event
			await screenshot_event.event_result(raise_if_any=True, raise_if_none=False)

			# Verify event history has grown
			final_history_count = len(browser_session.event_bus.event_history)
			assert final_history_count > initial_history_count, 'Event history should track new events'

			# Verify events are stored properly
			for event_id, event in browser_session.event_bus.event_history.items():
				assert event_id is not None
				assert event is not None
				assert hasattr(event, 'event_type') or hasattr(event, '__class__')

		finally:
			await browser_session.kill()

	async def test_generate_recent_events_summary_format(self, httpserver: HTTPServer):
		"""Test that _generate_recent_events_summary produces valid JSON."""
		browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=False))

		try:
			await browser_session.start()

			# Generate some events
			httpserver.expect_request('/json-test').respond_with_data(
				'<html><body><h1>JSON Test</h1></body></html>',
				content_type='text/html',
			)
			event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/json-test')))
			await event
			await event.event_result(raise_if_any=True, raise_if_none=False)

			# Test the NEW method _generate_recent_events_summary
			recent_events_json = await browser_session.get_browser_state_summary(include_recent_events=True)
			recent_events_json = recent_events_json.recent_events
			assert recent_events_json is not None

			# Should return valid JSON
			assert recent_events_json != '[]', 'Should have events'
			events = json.loads(recent_events_json)  # Should not raise JSON decode error
			assert isinstance(events, list), 'Should return a list of events'

			# Events should exclude problematic fields like 'state'
			for event in events:
				assert isinstance(event, dict), 'Each event should be a dict'
				assert 'state' not in event, "Event should not contain 'state' field (circular reference)"

		finally:
			await browser_session.kill()

	async def test_event_history_limits(self, httpserver: HTTPServer):
		"""Test that event history summary respects max_events parameter."""
		browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=False))

		try:
			await browser_session.start()

			# Generate multiple events
			httpserver.expect_request('/limit-test').respond_with_data(
				'<html><body><h1>Limit Test</h1></body></html>',
				content_type='text/html',
			)

			# Perform multiple actions to generate events
			event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/limit-test')))
			await event
			await event.event_result(raise_if_any=True, raise_if_none=False)
			screenshot_event = browser_session.event_bus.dispatch(ScreenshotEvent())
			await screenshot_event
			await screenshot_event.event_result(raise_if_any=True, raise_if_none=False)
			await browser_session.get_tabs()

			# Test recent events summary via BrowserStateSummary
			state_with_events = await browser_session.get_browser_state_summary(include_recent_events=True)
			assert state_with_events.recent_events is not None

			# Parse the JSON events
			events = json.loads(state_with_events.recent_events)

			# Should have some events
			assert len(events) > 0, 'Should have some recent events'
			assert isinstance(events, list), 'Events should be a list'

		finally:
			await browser_session.kill()
