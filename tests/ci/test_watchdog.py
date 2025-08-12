"""Test browser watchdog integration and lifecycle."""

from typing import cast

import pytest

from browser_use.browser.events import (
	BrowserConnectedEvent,
	BrowserStartEvent,
	BrowserStopEvent,
	BrowserStoppedEvent,
	NavigateToUrlEvent,
	NavigationCompleteEvent,
	TabCreatedEvent,
)
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


@pytest.mark.asyncio
async def test_watchdog_integration_with_session_lifecycle():
	"""Test that all watchdogs work together during browser session lifecycle."""
	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)

	# Start browser via event
	session.event_bus.dispatch(BrowserStartEvent())

	# Wait for browser started event
	started_event: BrowserConnectedEvent = cast(
		BrowserConnectedEvent, await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)
	)
	assert started_event.cdp_url is not None

	# Create a test page to ensure watchdogs are monitoring
	session.event_bus.dispatch(NavigateToUrlEvent(url='about:blank', new_tab=True))

	# Wait for tab created event
	await session.event_bus.expect(TabCreatedEvent, timeout=2.0)

	# Navigate to a real page to generate some network activity
	session.event_bus.dispatch(NavigateToUrlEvent(url='data:text/html,<h1>Integration Test</h1>', new_tab=True))

	# Wait for navigation to complete successfully (proves watchdogs aren't interfering)
	# Use predicate to wait for the specific navigation event we care about
	nav_complete: NavigationCompleteEvent = cast(
		NavigationCompleteEvent,
		await session.event_bus.expect(
			NavigationCompleteEvent,
			predicate=lambda e: cast(NavigationCompleteEvent, e).url == 'data:text/html,<h1>Integration Test</h1>',
			timeout=5.0,
		),
	)
	assert nav_complete.url == 'data:text/html,<h1>Integration Test</h1>'
	assert nav_complete.error_message is None

	# Verify all watchdogs are still operational
	assert session._crash_watchdog is not None
	assert session._downloads_watchdog is not None
	assert session._security_watchdog is not None
	assert session._storage_state_watchdog is not None
	assert session._aboutblank_watchdog is not None

	# Stop browser via event
	session.event_bus.dispatch(BrowserStopEvent())

	# Wait for browser stopped event
	stopped_event: BrowserStoppedEvent = cast(
		BrowserStoppedEvent, await session.event_bus.expect(BrowserStoppedEvent, timeout=5.0)
	)
	assert stopped_event.reason is not None


@pytest.mark.asyncio
async def test_watchdog_event_handler_registration():
	"""Test that all watchdogs properly register their event handlers."""
	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)

	try:
		# Start browser
		session.event_bus.dispatch(BrowserStartEvent())
		await session.event_bus.expect(BrowserConnectedEvent, timeout=5.0)

		# Verify event handlers are registered by checking event bus
		# The event bus should have multiple handlers registered
		event_bus = session.event_bus

		# Each watchdog should have registered handlers
		# We can't easily inspect the internal handler registry, but we can verify
		# the watchdogs were initialized with the event bus
		for watchdog in [
			session._crash_watchdog,
			session._downloads_watchdog,
			session._security_watchdog,
			session._storage_state_watchdog,
			session._aboutblank_watchdog,
		]:
			if watchdog is not None:
				assert watchdog.event_bus is event_bus
				assert hasattr(watchdog, 'LISTENS_TO')
				assert hasattr(watchdog, 'EMITS')

	finally:
		# Stop browser
		session.event_bus.dispatch(BrowserStopEvent())
		await session.event_bus.expect(BrowserStoppedEvent, timeout=5.0)
