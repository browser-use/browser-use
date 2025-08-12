"""Test navigation and security functionality."""

from typing import cast

import pytest

from browser_use.browser.events import (
	BrowserConnectedEvent,
	BrowserErrorEvent,
	BrowserStartEvent,
	BrowserStopEvent,
	BrowserStoppedEvent,
	NavigateToUrlEvent,
	TabCreatedEvent,
)
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


@pytest.mark.asyncio
async def test_navigation_tab_created_events():
	"""Test that BrowserSession properly emits TabCreatedEvent when pages are added."""
	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)

	# Track TabCreatedEvents
	tab_created_events = []
	session.event_bus.on(TabCreatedEvent, lambda e: tab_created_events.append(e))

	try:
		# Start browser
		session.event_bus.dispatch(BrowserStartEvent())
		await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

		# Verify security watchdog was created (replaces navigation watchdog)
		assert hasattr(session, '_security_watchdog'), 'SecurityWatchdog should be created'
		assert session._security_watchdog is not None, 'SecurityWatchdog should not be None'

		# Create first tab - should emit TabCreatedEvent
		session.event_bus.dispatch(NavigateToUrlEvent(url='data:text/html,<h1>Tab 1</h1>', new_tab=True))

		# Wait for first TabCreatedEvent
		first_event: TabCreatedEvent = cast(TabCreatedEvent, await session.event_bus.expect(TabCreatedEvent, timeout=3.0))
		# The first event might be for about:blank or the target URL depending on timing
		assert first_event.tab_index >= 0
		assert isinstance(first_event.url, str)

		# Create second tab - should emit another TabCreatedEvent
		session.event_bus.dispatch(NavigateToUrlEvent(url='data:text/html,<h1>Tab 2</h1>', new_tab=True))

		# Wait for second TabCreatedEvent
		second_event: TabCreatedEvent = cast(TabCreatedEvent, await session.event_bus.expect(TabCreatedEvent, timeout=3.0))
		assert second_event.tab_index >= 0
		assert isinstance(second_event.url, str)

		# Verify we have at least 2 TabCreatedEvents
		assert len(tab_created_events) >= 2, f'Expected at least 2 TabCreatedEvents, got {len(tab_created_events)}'

		# Verify the events have different tab indices (unless they're reusing the same tab)
		unique_tab_indexes = {event.tab_index for event in tab_created_events}
		assert len(unique_tab_indexes) >= 2, 'Should have at least two unique tab indices'

	finally:
		# Stop browser
		session.event_bus.dispatch(BrowserStopEvent())
		await session.event_bus.expect(BrowserStoppedEvent, timeout=5.0)


@pytest.mark.asyncio
async def test_security_watchdog_enforcement():
	"""Test that the SecurityWatchdog enforces allowed_domains security."""
	# Create a profile with restricted domains
	profile = BrowserProfile(
		headless=True,
		allowed_domains=['example.com', 'httpbin.org'],  # Only allow these domains
	)
	session = BrowserSession(browser_profile=profile)

	# Track BrowserErrorEvents
	error_events = []
	session.event_bus.on(BrowserErrorEvent, lambda e: error_events.append(e))

	try:
		# Start browser
		session.event_bus.dispatch(BrowserStartEvent())
		await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

		# Verify security watchdog was created and has security check
		assert hasattr(session, '_security_watchdog'), 'SecurityWatchdog should be created'
		assert session._security_watchdog is not None, 'SecurityWatchdog should not be None'

		# Test that allowed domains work
		allowed_url = 'https://httpbin.org/get'
		allowed = session._security_watchdog._is_url_allowed(allowed_url)
		assert allowed, f'Should allow {allowed_url}'

		# Test that disallowed domains are blocked
		disallowed_url = 'https://malicious-site.com/bad'
		disallowed = session._security_watchdog._is_url_allowed(disallowed_url)
		assert not disallowed, f'Should block {disallowed_url}'

		# Test internal URLs are always allowed
		internal_urls = ['about:blank', 'chrome://newtab/', 'chrome://new-tab-page/']
		for url in internal_urls:
			assert session._security_watchdog._is_url_allowed(url), f'Should allow internal URL: {url}'

		# Test glob patterns work
		profile_with_glob = BrowserProfile(headless=True, allowed_domains=['*.github.com'])
		session._security_watchdog.browser_session.browser_profile = profile_with_glob

		assert session._security_watchdog._is_url_allowed('https://api.github.com/repos'), 'Should allow subdomain'
		assert session._security_watchdog._is_url_allowed('https://github.com/user'), 'Should allow main domain'
		assert not session._security_watchdog._is_url_allowed('https://evil.com/github.com'), 'Should block non-matching domain'

	finally:
		# Stop browser
		session.event_bus.dispatch(BrowserStopEvent())
		await session.event_bus.expect(BrowserStoppedEvent, timeout=5.0)


@pytest.mark.asyncio
async def test_navigation_watchdog_agent_focus_tracking():
	"""Test that NavigationWatchdog properly tracks agent focus between tabs."""
	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)

	try:
		# Start browser
		session.event_bus.dispatch(BrowserStartEvent())
		await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

		# Get navigation watchdog
		nav_watchdog = session._navigation_watchdog
		assert nav_watchdog is not None

		# Initial tab should be tab 0
		assert nav_watchdog.agent_tab_index == 0

		# Create a new tab
		session.event_bus.dispatch(NavigateToUrlEvent(url='data:text/html,<h1>New Tab</h1>', new_tab=True))
		await session.event_bus.expect(TabCreatedEvent, timeout=3.0)

		# Agent focus should have moved to the new tab
		# Give it a moment for focus to update
		import asyncio

		await asyncio.sleep(0.2)

		# The agent focus should be on a tab index > 0
		assert nav_watchdog.agent_tab_index > 0

	finally:
		# Stop browser
		session.event_bus.dispatch(BrowserStopEvent())
		await session.event_bus.expect(BrowserStoppedEvent, timeout=5.0)
