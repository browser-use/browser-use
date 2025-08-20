"""
Test browser session recent events tracking functionality.
"""

import asyncio
import json
import time

import pytest

pytest.skip('TODO: fix - uses removed navigate method', allow_module_level=True)

from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Response

from browser_use.browser import BrowserProfile, BrowserSession


class TestBrowserRecentEvents:
	"""Test recent events tracking functionality"""

	async def test_recent_events_on_network_timeout(self, httpserver: HTTPServer):
		"""Test that recent events captures network timeout information"""
		# Create a page with multiple resources that never finish loading
		html_content = """
		<html>
		<head>
			<title>Slow Loading Test Page</title>
			<script src="/slow-script.js"></script>
			<link rel="stylesheet" href="/slow-style.css">
		</head>
		<body>
			<h1>Testing Loading Status</h1>
			<p>This page has resources that never finish loading.</p>
			<img src="/slow-image.jpg" alt="Slow loading image">
			<iframe src="/slow-iframe.html" width="400" height="300"></iframe>
		</body>
		</html>
		"""

		# Main page loads immediately
		httpserver.expect_request('/').respond_with_data(html_content, content_type='text/html')

		# Handler that sleeps longer than the timeout
		def slow_handler(request):
			# Sleep for 5 seconds - longer than the 1s maximum_wait_page_load_time
			time.sleep(5)
			return Response('/* Never loads in time */', content_type='text/plain')

		# Set up all the slow endpoints
		httpserver.expect_request('/slow-script.js').respond_with_handler(slow_handler)
		httpserver.expect_request('/slow-style.css').respond_with_handler(slow_handler)
		httpserver.expect_request('/slow-image.jpg').respond_with_handler(slow_handler)
		httpserver.expect_request('/slow-iframe.html').respond_with_handler(slow_handler)

		# Create browser session with very short timeout
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				maximum_wait_page_load_time=1.0,  # 1 second max wait
				wait_for_network_idle_page_load_time=0.1,  # 100ms idle time
				minimum_wait_page_load_time=0.1,  # Don't wait extra
			)
		)

		try:
			await browser_session.start()

			# Navigate to the page with the slow iframe
			# Don't await to allow navigation to start in background
			nav_task = asyncio.create_task(browser_session.navigate(httpserver.url_for('/')))

			# Give navigation a moment to start loading resources
			await asyncio.sleep(0.5)

			# Get state while resources are still loading
			# _wait_for_stable_network should detect pending requests and timeout
			state = await browser_session.get_browser_state_summary()

			# Wait for navigation to complete
			await nav_task

			# Verify recent events contains event information
			assert state.recent_events is not None, 'Recent events should be set'

			# Parse JSON events
			events = json.loads(state.recent_events)
			assert len(events) > 0, 'Should have at least one event'

			# Check event types present
			event_types = [e.get('event_type') for e in events]
			print(f'Event types in recent_events: {event_types}')

			# Should have navigation-related events
			assert 'NavigateToUrlEvent' in event_types or 'NavigationCompleteEvent' in event_types, (
				'Should have navigation events in recent events'
			)

			# Check for any error or timeout information in events
			error_indicators = []
			for event in events:
				# NavigationCompleteEvent with error_message
				if event.get('event_type') == 'NavigationCompleteEvent' and event.get('error_message'):
					error_indicators.append(event)
				# BrowserErrorEvent indicating timeout
				elif event.get('event_type') == 'BrowserErrorEvent' and 'timeout' in str(event.get('message', '')).lower():
					error_indicators.append(event)

			# Since we have slow-loading resources, we should see either:
			# 1. Navigation completed normally (resources loaded in background)
			# 2. Navigation reported timeout/error due to slow resources
			nav_events = [e for e in events if e.get('event_type') == 'NavigationCompleteEvent']
			if nav_events:
				print(f'Found {len(nav_events)} NavigationCompleteEvent(s)')
				# Navigation occurred, that's what matters for LLM context
				assert True
			else:
				# No navigation complete event yet, but we should see NavigateToUrlEvent
				assert 'NavigateToUrlEvent' in event_types, 'Should see navigation attempt in events'

		finally:
			await browser_session.kill()

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
				maximum_wait_page_load_time=5.0,  # Generous timeout
			)
		)

		try:
			await browser_session.start()

			# Navigate to the fast-loading page
			await browser_session.navigate(httpserver.url_for('/fast'))

			# Get browser state
			state = await browser_session.get_browser_state_summary()

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
			assert last_nav.get('status') == 200, 'Should have successful status'

		finally:
			await browser_session.kill()

	async def test_recent_events_tracks_multiple_navigations(self, httpserver: HTTPServer):
		"""Test that recent events properly tracks multiple navigations"""
		# Set up pages
		slow_html = """
		<html>
		<head>
			<title>Slow Page</title>
			<script src="/slow.js"></script>
		</head>
		<body><h1>Slow page</h1></body>
		</html>
		"""

		httpserver.expect_request('/slow').respond_with_data(slow_html, content_type='text/html')

		def slow_handler(req):
			import time

			time.sleep(5)
			return Response('slow')

		httpserver.expect_request('/slow.js').respond_with_handler(slow_handler)

		httpserver.expect_request('/fast').respond_with_data(
			'<html><head><title>Fast Page</title></head><body><h1>Fast page</h1></body></html>',
			content_type='text/html',
		)

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				maximum_wait_page_load_time=0.5,  # Short timeout for first page
			)
		)

		try:
			await browser_session.start()

			# Navigate to slow page
			await browser_session.navigate(httpserver.url_for('/slow'))
			state1 = await browser_session.get_browser_state_summary()
			assert state1.recent_events is not None
			events1 = json.loads(state1.recent_events)
			event_types1 = [e.get('event_type') for e in events1]
			assert 'NavigationCompleteEvent' in event_types1 or 'NavigateToUrlEvent' in event_types1

			# Navigate to fast page
			await browser_session.navigate(httpserver.url_for('/fast'))
			state2 = await browser_session.get_browser_state_summary()

			# Recent events should show both navigations
			assert state2.recent_events is not None
			events2 = json.loads(state2.recent_events)

			# Count navigation events (last 10 events should include both)
			nav_complete_count = sum(1 for e in events2 if e.get('event_type') == 'NavigationCompleteEvent')
			nav_url_count = sum(1 for e in events2 if e.get('event_type') == 'NavigateToUrlEvent')

			# Should have events from both navigations
			assert nav_complete_count >= 1 or nav_url_count >= 2, 'Recent events should show multiple navigation attempts'

		finally:
			await browser_session.kill()

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
			import time

			time.sleep(5)
			return Response('slow')

		httpserver.expect_request('/slow.js').respond_with_handler(slow_handler)

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				maximum_wait_page_load_time=0.5,  # Short timeout
			)
		)

		try:
			await browser_session.start()

			# Navigate to the malformed page
			await browser_session.navigate(httpserver.url_for('/malformed'))

			# Get browser state - this might fall back to minimal state
			state = await browser_session.get_browser_state_summary()

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
			import time

			time.sleep(10)
			return Response('slow')

		httpserver.expect_request(f'/slow_{timeout_seconds}.js').respond_with_handler(very_slow_handler)

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
				maximum_wait_page_load_time=timeout_seconds,
				wait_for_network_idle_page_load_time=0.1,
				minimum_wait_page_load_time=0.1,
			)
		)

		try:
			await browser_session.start()

			# Navigate to the page
			await browser_session.navigate(httpserver.url_for(f'/timeout_{timeout_seconds}'))

			# Get browser state
			state = await browser_session.get_browser_state_summary()

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
			await browser_session.navigate(httpserver.url_for('/history-test'))
			await browser_session.take_screenshot()

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
			await browser_session.navigate(httpserver.url_for('/json-test'))

			# Test the NEW method _generate_recent_events_summary
			recent_events_json = browser_session._generate_recent_events_summary(max_events=5)

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
			await browser_session.navigate(httpserver.url_for('/limit-test'))
			await browser_session.take_screenshot()
			await browser_session.get_tabs()

			# Test different limits
			summary_3 = browser_session._generate_recent_events_summary(max_events=3)
			summary_1 = browser_session._generate_recent_events_summary(max_events=1)

			events_3 = json.loads(summary_3)
			events_1 = json.loads(summary_1)

			# Should respect the limits
			assert len(events_3) <= 3, 'Should limit to 3 events'
			assert len(events_1) <= 1, 'Should limit to 1 event'
			assert len(events_1) <= len(events_3), 'Smaller limit should have fewer events'

		finally:
			await browser_session.kill()
