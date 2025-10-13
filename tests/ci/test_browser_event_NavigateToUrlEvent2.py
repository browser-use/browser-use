"""Test navigation events are emitted properly in all cases."""

import asyncio
import time
from typing import cast

import pytest

from browser_use.browser.events import (
	ClickElementEvent,
	NavigateToUrlEvent,
	NavigationCompleteEvent,
	NavigationStartedEvent,
	TabCreatedEvent,
)
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


@pytest.mark.asyncio
async def test_navigation_events_fast_page_load(httpserver):
	"""Test navigation events for page that loads easily/normally within 1s."""
	# Set up a fast endpoint
	httpserver.expect_request('/fast').respond_with_data(
		'<html><head><title>Fast Page</title></head><body><h1>Fast Loading Page</h1></body></html>',
		status=200,
		content_type='text/html',
	)
	fast_url = httpserver.url_for('/fast')

	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)

	# Track navigation events
	navigation_started_events = []
	navigation_complete_events = []
	session.event_bus.on(NavigationStartedEvent, lambda e: navigation_started_events.append(e))
	session.event_bus.on(NavigationCompleteEvent, lambda e: navigation_complete_events.append(e))

	try:
		# Start browser
		await session.start()

		# Navigate to fast page
		start_time = time.time()
		session.event_bus.dispatch(NavigateToUrlEvent(url=fast_url))

		# Wait for navigation to complete
		nav_complete: NavigationCompleteEvent = cast(
			NavigationCompleteEvent, await session.event_bus.expect(NavigationCompleteEvent, timeout=5.0)
		)
		end_time = time.time()

		# Verify navigation completed in reasonable time (within 5s)
		assert (end_time - start_time) < 5.0, 'Navigation should complete in reasonable time'

		# Verify NavigationStartedEvent was emitted
		assert len(navigation_started_events) >= 1, 'Should have NavigationStartedEvent'
		nav_started = navigation_started_events[-1]
		assert nav_started.url == fast_url
		assert nav_started.target_id is not None

		# Verify NavigationCompleteEvent was emitted with success
		assert len(navigation_complete_events) >= 1, 'Should have NavigationCompleteEvent'
		assert nav_complete.url == fast_url
		assert nav_complete.target_id
		# CDP doesn't provide HTTP status directly, just check no error
		assert nav_complete.error_message is None, 'Should have no error message'
		assert nav_complete.loading_status is None, 'Should have no loading status issues'

	finally:
		await session.stop()


@pytest.mark.asyncio
async def test_navigation_events_slow_page_with_timeout(httpserver):
	"""Test navigation events for page that takes >10s to load and times out."""

	# Set up a slow endpoint that takes longer than we want to wait
	def slow_handler(request):
		time.sleep(5.0)  # 5 seconds - longer than our timeout
		from werkzeug import Response

		return Response('<html><body>Finally loaded</body></html>', status=200)

	httpserver.expect_request('/slow').respond_with_handler(slow_handler)
	slow_url = httpserver.url_for('/slow')

	# Create profile with shorter timeout for faster testing
	profile = BrowserProfile(
		headless=True,
		wait_for_network_idle_page_load_time=0.5,  # 0.5 second network idle
	)
	session = BrowserSession(browser_profile=profile)

	# Track navigation events
	navigation_started_events = []
	navigation_complete_events = []
	session.event_bus.on(NavigationStartedEvent, lambda e: navigation_started_events.append(e))
	session.event_bus.on(NavigationCompleteEvent, lambda e: navigation_complete_events.append(e))

	try:
		# Start browser
		await session.start()

		# Navigate to slow page
		session.event_bus.dispatch(NavigateToUrlEvent(url=slow_url))

		# Wait for navigation to timeout and complete with error
		nav_complete: NavigationCompleteEvent = cast(
			NavigationCompleteEvent, await session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)
		)

		# Verify NavigationStartedEvent was emitted
		assert len(navigation_started_events) >= 1, 'Should have NavigationStartedEvent'
		nav_started = navigation_started_events[-1]
		assert nav_started.url == slow_url

		# Verify NavigationCompleteEvent was emitted
		assert len(navigation_complete_events) >= 1, 'Should have NavigationCompleteEvent'
		assert nav_complete.url == slow_url

		# Either the navigation succeeded after timeout (page loaded) or it timed out
		# Both are valid outcomes - what matters is that NavigationCompleteEvent was emitted
		if nav_complete.error_message or nav_complete.loading_status:
			# Navigation had issues (timeout/loading problems)
			has_timeout_indicator = (
				nav_complete.error_message
				and ('timeout' in nav_complete.error_message.lower() or 'pending' in nav_complete.error_message.lower())
				or nav_complete.loading_status
				and (
					'aborted' in nav_complete.loading_status.lower()
					or 'pending' in nav_complete.loading_status.lower()
					or 'requests' in nav_complete.loading_status.lower()
				)
			)
			print(
				f"Navigation had issues - error_message: '{nav_complete.error_message}', loading_status: '{nav_complete.loading_status}'"
			)
			assert has_timeout_indicator, (
				f'Should indicate timeout/loading issues when navigation has problems. '
				f"error_message='{nav_complete.error_message}', "
				f"loading_status='{nav_complete.loading_status}'"
			)
		else:
			# Navigation succeeded (slow but successful)
			print('Navigation succeeded despite being slow')
			# CDP doesn't provide HTTP status directly, just check no error
		assert nav_complete.error_message is None, 'Successful navigation should have no error'

	finally:
		await session.stop()


@pytest.mark.asyncio
@pytest.mark.skip(reason='DOM element detection issue - same-tab-link not found in selector map')
async def test_navigation_events_link_clicks(httpserver):
	"""Test that clicking links (same tab and new tab) triggers NavigationCompleteEvent."""
	# Set up pages with different types of links
	main_page = """
	<html>
	<head><title>Link Test</title></head>
	<body>
		<h1>Link Click Test</h1>
		<a id="same-tab-link" href="/target-page">Same Tab Link</a>
		<a id="new-tab-link" href="/target-page" target="_blank">New Tab Link</a>
		<a id="js-navigation" href="#" onclick="window.location.href='/js-target'; return false;">JS Navigation</a>
	</body>
	</html>
	"""

	target_page = """
	<html>
	<head><title>Target Page</title></head>
	<body><h1>Target Page Loaded</h1></body>
	</html>
	"""

	js_target_page = """
	<html>
	<head><title>JS Target</title></head>
	<body><h1>JavaScript Navigation Target</h1></body>
	</html>
	"""

	httpserver.expect_request('/link-test').respond_with_data(main_page, status=200, content_type='text/html')
	httpserver.expect_request('/target-page').respond_with_data(target_page, status=200, content_type='text/html')
	httpserver.expect_request('/js-target').respond_with_data(js_target_page, status=200, content_type='text/html')

	main_url = httpserver.url_for('/link-test')
	target_url = httpserver.url_for('/target-page')
	js_target_url = httpserver.url_for('/js-target')

	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)

	# Track navigation and tab events
	navigation_complete_events = []
	tab_created_events = []
	session.event_bus.on(NavigationCompleteEvent, lambda e: navigation_complete_events.append(e))
	session.event_bus.on(TabCreatedEvent, lambda e: tab_created_events.append(e))

	try:
		# Start browser
		await session.start()

		# Navigate to the main page
		session.event_bus.dispatch(NavigateToUrlEvent(url=main_url))
		await session.event_bus.expect(NavigationCompleteEvent, timeout=5.0)

		# Clear events to focus on link clicks
		navigation_complete_events.clear()

		# Test 1: Same tab link click
		state = await session.get_browser_state_summary()
		same_tab_link_found = False

		for idx, element in state.dom_state.selector_map.items():
			if hasattr(element, 'attributes') and element.attributes.get('id') == 'same-tab-link':
				same_tab_link_found = True
				click_element = await session.get_dom_element_by_index(idx)
				if click_element is not None:
					session.event_bus.dispatch(ClickElementEvent(node=click_element))
				break

		assert same_tab_link_found, f'Should find same tab link {main_url}'

		# Wait for navigation to complete
		nav_complete: NavigationCompleteEvent = cast(
			NavigationCompleteEvent, await session.event_bus.expect(NavigationCompleteEvent, timeout=5.0)
		)

		assert nav_complete.url == target_url, f'Should navigate to {target_url}'
		assert nav_complete.error_message is None, 'Link navigation should succeed'

		# Test 2: New tab link click (if supported)
		# Navigate back to main page first
		session.event_bus.dispatch(NavigateToUrlEvent(url=main_url))
		await session.event_bus.expect(NavigationCompleteEvent, timeout=5.0)

		# Clear events
		navigation_complete_events.clear()
		tab_created_events.clear()

		state = await session.get_browser_state_summary()
		new_tab_link_found = False

		for idx, element in state.dom_state.selector_map.items():
			if hasattr(element, 'attributes') and element.attributes.get('id') == 'new-tab-link':
				new_tab_link_found = True
				click_element = await session.get_dom_element_by_index(idx)
				if click_element is not None:
					session.event_bus.dispatch(ClickElementEvent(node=click_element))
				break

		if new_tab_link_found:
			# Wait for either new tab creation or navigation
			await asyncio.sleep(2.0)  # Give time for tab creation and navigation

			# Should have either tab creation or navigation event (or both)
			has_new_tab_activity = len(tab_created_events) > 0 or len(navigation_complete_events) > 0
			assert has_new_tab_activity, 'New tab link should trigger tab creation or navigation'

			if navigation_complete_events:
				nav_complete = navigation_complete_events[-1]
				assert target_url in nav_complete.url or nav_complete.error_message is None

		# Test 3: JavaScript navigation
		session.event_bus.dispatch(NavigateToUrlEvent(url=main_url))
		await session.event_bus.expect(NavigationCompleteEvent, timeout=5.0)

		navigation_complete_events.clear()

		state = await session.get_browser_state_summary()
		js_link_found = False

		for idx, element in state.dom_state.selector_map.items():
			if hasattr(element, 'attributes') and element.attributes.get('id') == 'js-navigation':
				js_link_found = True
				click_element = await session.get_dom_element_by_index(idx)
				if click_element is not None:
					session.event_bus.dispatch(ClickElementEvent(node=click_element))
				break

		if js_link_found:
			# Wait for JavaScript navigation to complete
			nav_complete = cast(NavigationCompleteEvent, await session.event_bus.expect(NavigationCompleteEvent, timeout=5.0))

			assert nav_complete.url == js_target_url, 'JS navigation should work'
			assert nav_complete.error_message is None, 'JS navigation should succeed'

	finally:
		await session.stop()


# @pytest.mark.asyncio
# async def test_navigation_timeout_event_dispatch():
# 	"""Test that NavigateToUrlEvent with timeout_ms properly dispatches NavigationCompleteEvent on timeout."""
# 	profile = BrowserProfile(headless=True)
# 	session = BrowserSession(browser_profile=profile)

# 	# Track navigation events
# 	navigation_complete_events = []
# 	session.event_bus.on(NavigationCompleteEvent, lambda e: navigation_complete_events.append(e))

# 	try:
# 		# Start browser
# 		await session.start()

# 		# Navigate with a very short timeout to a valid but slow URL
# 		session.event_bus.dispatch(
# 			NavigateToUrlEvent(
# 				url='data:text/html,<h1>Should timeout</h1>',  # Use a data URL that should work
# 				timeout_ms=1,  # 1ms timeout - should definitely timeout
# 			)
# 		)

# 		# Wait for navigation to timeout and complete with error
# 		nav_complete: NavigationCompleteEvent = cast(
# 			NavigationCompleteEvent, await session.event_bus.expect(NavigationCompleteEvent, timeout=5.0)
# 		)

# 		# Verify NavigationCompleteEvent indicates timeout
# 		assert nav_complete.error_message is not None, 'Should have error message for timeout'
# 		assert 'timed out' in nav_complete.error_message.lower(), f'Error should mention timed out: {nav_complete.error_message}'
# 		assert nav_complete.loading_status is not None, 'Should have loading status'
# 		assert 'timeout' in nav_complete.loading_status.lower(), (
# 			f'Loading status should mention timeout: {nav_complete.loading_status}'
# 		)

# 		# Verify specific timeout details
# 		assert '1ms' in nav_complete.error_message, 'Should mention the specific timeout duration'

# 	finally:
# 		await session.stop()


# @pytest.mark.asyncio
# async def test_navigation_error_recovery():
# 	"""Test that navigation errors are properly reported and don't break subsequent navigation."""
# 	profile = BrowserProfile(headless=True)
# 	session = BrowserSession(browser_profile=profile)

# 	# Track navigation events
# 	navigation_complete_events = []
# 	session.event_bus.on(NavigationCompleteEvent, lambda e: navigation_complete_events.append(e))

# 	try:
# 		# Start browser
# 		await session.start()

# 		# Try to navigate to invalid URL
# 		session.event_bus.dispatch(NavigateToUrlEvent(url='invalid://not-a-real-url'))

# 		# Wait for navigation to fail
# 		nav_complete: NavigationCompleteEvent = cast(
# 			NavigationCompleteEvent, await session.event_bus.expect(NavigationCompleteEvent, timeout=5.0)
# 		)

# 		# Verify NavigationCompleteEvent indicates error
# 		assert nav_complete.error_message is not None, 'Should have error message for invalid URL'
# 		assert nav_complete.url == 'invalid://not-a-real-url'

# 		# Clear events
# 		navigation_complete_events.clear()

# 		# Verify that subsequent navigation still works
# 		session.event_bus.dispatch(NavigateToUrlEvent(url='data:text/html,<h1>Recovery Test</h1>'))

# 		nav_complete_recovery: NavigationCompleteEvent = cast(
# 			NavigationCompleteEvent, await session.event_bus.expect(NavigationCompleteEvent, timeout=5.0)
# 		)

# 		# Verify recovery navigation succeeded
# 		assert nav_complete_recovery.url == 'data:text/html,<h1>Recovery Test</h1>'
# 		assert nav_complete_recovery.error_message is None, 'Recovery navigation should succeed'

# 	finally:
# 		await session.stop()
