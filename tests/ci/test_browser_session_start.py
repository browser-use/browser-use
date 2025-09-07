"""
Test script for BrowserSession.start() method to ensure proper initialization,
concurrency handling, and error handling.

Tests cover:
- Calling .start() on a session that's already started
- Simultaneously calling .start() from two parallel coroutines
- Calling .start() on a session that's started but has a closed browser connection
- Calling .close() on a session that hasn't been started yet
"""

import asyncio
import logging

import pytest

from browser_use.browser.profile import (
	BROWSERUSE_DEFAULT_CHANNEL,
	BrowserChannel,
	BrowserProfile,
)
from browser_use.browser.session import BrowserSession
from browser_use.config import CONFIG

# Set up test logging
logger = logging.getLogger('browser_session_start_tests')
# logger.setLevel(logging.DEBUG)


# run with pytest -k test_user_data_dir_not_allowed_to_corrupt_default_profile


class TestBrowserSessionStart:
	"""Tests for BrowserSession.start() method initialization and concurrency."""

	@pytest.fixture(scope='module')
	async def browser_profile(self):
		"""Create and provide a BrowserProfile with headless mode."""
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		yield profile

	@pytest.fixture(scope='function')
	async def browser_session(self, browser_profile):
		"""Create a BrowserSession instance without starting it."""
		session = BrowserSession(browser_profile=browser_profile)
		yield session
		await session.kill()

	async def test_start_already_started_session(self, browser_session):
		"""Test calling .start() on a session that's already started."""
		# logger.info('Testing start on already started session')

		# Start the session for the first time
		await browser_session.start()
		assert browser_session._cdp_client_root is not None

		# Start the session again - should return immediately without re-initialization
		await browser_session.start()
		assert browser_session._cdp_client_root is not None

	# @pytest.mark.skip(reason="Race condition - DOMWatchdog tries to inject scripts into tab that's being closed")
	# async def test_page_lifecycle_management(self, browser_session: BrowserSession):
	# 	"""Test session handles page lifecycle correctly."""
	# 	# logger.info('Testing page lifecycle management')

	# 	# Start the session and get initial state
	# 	await browser_session.start()
	# 	initial_tabs = await browser_session.get_tabs()
	# 	initial_count = len(initial_tabs)

	# 	# Get current tab info
	# 	current_url = await browser_session.get_current_page_url()
	# 	assert current_url is not None

	# 	# Get current tab ID
	# 	current_tab_id = browser_session.agent_focus.target_id if browser_session.agent_focus else None
	# 	assert current_tab_id is not None

	# 	# Close the current tab using the event system
	# 	from browser_use.browser.events import CloseTabEvent

	# 	close_event = browser_session.event_bus.dispatch(CloseTabEvent(target_id=current_tab_id))
	# 	await close_event

	# 	# Operations should still work - may create new page or use existing
	# 	tabs_after_close = await browser_session.get_tabs()
	# 	assert isinstance(tabs_after_close, list)

	# 	# Create a new tab explicitly
	# 	event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url='about:blank', new_tab=True))
	# 	await event
	# 	await event.event_result(raise_if_any=True, raise_if_none=False)

	# 	# Should have at least one tab now
	# 	final_tabs = await browser_session.get_tabs()
	# 	assert len(final_tabs) >= 1

	async def test_user_data_dir_not_allowed_to_corrupt_default_profile(self):
		"""Test user_data_dir handling for different browser channels and version mismatches."""
		# Test 1: Chromium with default user_data_dir and default channel should work fine
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR,
				channel=BROWSERUSE_DEFAULT_CHANNEL,  # chromium
				keep_alive=False,
			),
		)

		try:
			await session.start()
			assert session._cdp_client_root is not None
			# Verify the user_data_dir wasn't changed
			assert session.browser_profile.user_data_dir == CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR
		finally:
			await session.kill()

		# Test 2: Chrome with default user_data_dir should automatically change dir
		profile2 = BrowserProfile(
			headless=True,
			user_data_dir=CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR,
			channel=BrowserChannel.CHROME,
			keep_alive=False,
		)

		# The validator should have changed the user_data_dir to avoid corruption
		assert profile2.user_data_dir != CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR
		assert profile2.user_data_dir == CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR.parent / 'default-chrome'

		# Test 3: Edge with default user_data_dir should also change
		profile3 = BrowserProfile(
			headless=True,
			user_data_dir=CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR,
			channel=BrowserChannel.MSEDGE,
			keep_alive=False,
		)

		assert profile3.user_data_dir != CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR
		assert profile3.user_data_dir == CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR.parent / 'default-msedge'


class TestBrowserSessionReusePatterns:
	"""Tests for all browser re-use patterns documented in docs/customize/real-browser.mdx"""

	async def test_sequential_agents_same_profile_different_browser(self, mock_llm):
		"""Test Sequential Agents, Same Profile, Different Browser pattern"""
		from browser_use import Agent
		from browser_use.browser.profile import BrowserProfile

		# Create a reusable profile
		reused_profile = BrowserProfile(
			user_data_dir=None,  # Use temp dir for testing
			headless=True,
		)

		# First agent
		agent1 = Agent(
			task='The first task...',
			llm=mock_llm,
			browser_profile=reused_profile,
		)
		await agent1.run()

		# Verify first agent's session is closed
		assert agent1.browser_session is not None
		assert not agent1.browser_session._cdp_client_root is not None

		# Second agent with same profile
		agent2 = Agent(
			task='The second task...',
			llm=mock_llm,
			browser_profile=reused_profile,
			# Disable memory for tests
		)
		await agent2.run()

		# Verify second agent created a new session
		assert agent2.browser_session is not None
		assert agent1.browser_session is not agent2.browser_session
		assert not agent2.browser_session._cdp_client_root is not None

	async def test_sequential_agents_same_profile_same_browser(self, mock_llm):
		"""Test Sequential Agents, Same Profile, Same Browser pattern"""
		from browser_use import Agent, BrowserSession

		# Create a reusable session with keep_alive
		reused_session = BrowserSession(
			browser_profile=BrowserProfile(
				user_data_dir=None,  # Use temp dir for testing
				headless=True,
				keep_alive=True,  # Don't close browser after agent.run()
			),
		)

		try:
			# Start the session manually (agents will reuse this initialized session)
			await reused_session.start()

			# First agent
			agent1 = Agent(
				task='The first task...',
				llm=mock_llm,
				browser_session=reused_session,
				# Disable memory for tests
			)
			await agent1.run()

			# Verify session is still alive
			assert reused_session._cdp_client_root is not None

			# Second agent reusing the same session
			agent2 = Agent(
				task='The second task...',
				llm=mock_llm,
				browser_session=reused_session,
				# Disable memory for tests
			)
			await agent2.run()

			# Verify same browser was used (using __eq__ to check browser_pid, cdp_url)
			assert agent1.browser_session == agent2.browser_session
			assert agent1.browser_session == reused_session
			assert reused_session._cdp_client_root is not None

		finally:
			await reused_session.kill()


class TestBrowserSessionEventSystem:
	"""Tests for the new event system integration in BrowserSession."""

	@pytest.fixture(scope='function')
	async def browser_session(self):
		"""Create a BrowserSession instance for event system testing."""
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		session = BrowserSession(browser_profile=profile)
		yield session
		await session.kill()

	async def test_event_bus_initialization(self, browser_session):
		"""Test that event bus is properly initialized with unique name."""
		# Event bus should be created during __init__
		assert browser_session.event_bus is not None
		assert browser_session.event_bus.name.startswith('EventBus_')
		# Event bus name format may vary, just check it exists

	async def test_event_handlers_registration(self, browser_session: BrowserSession):
		"""Test that event handlers are properly registered."""
		# Attach all watchdogs to register their handlers
		await browser_session.attach_all_watchdogs()

		# Check that handlers are registered in the event bus
		from browser_use.browser.events import (
			BrowserStartEvent,
			BrowserStateRequestEvent,
			BrowserStopEvent,
			ClickElementEvent,
			CloseTabEvent,
			ScreenshotEvent,
			ScrollEvent,
			TypeTextEvent,
		)

		# These event types should have handlers registered
		event_types_with_handlers = [
			BrowserStartEvent,
			BrowserStopEvent,
			ClickElementEvent,
			TypeTextEvent,
			ScrollEvent,
			CloseTabEvent,
			BrowserStateRequestEvent,
			ScreenshotEvent,
		]

		for event_type in event_types_with_handlers:
			handlers = browser_session.event_bus.handlers.get(event_type.__name__, [])
			assert len(handlers) > 0, f'No handlers registered for {event_type.__name__}'

	async def test_direct_event_dispatching(self, browser_session):
		"""Test direct event dispatching without using the public API."""
		from browser_use.browser.events import BrowserConnectedEvent, BrowserStartEvent

		# Dispatch BrowserStartEvent directly
		start_event = browser_session.event_bus.dispatch(BrowserStartEvent())

		# Wait for event to complete
		await start_event

		# Check if BrowserConnectedEvent was dispatched
		assert browser_session._cdp_client_root is not None

		# Check event history
		event_history = list(browser_session.event_bus.event_history.values())
		assert len(event_history) >= 2  # BrowserStartEvent + BrowserConnectedEvent + others

		# Find the BrowserConnectedEvent in history
		started_events = [e for e in event_history if isinstance(e, BrowserConnectedEvent)]
		assert len(started_events) >= 1
		assert started_events[0].cdp_url is not None

	async def test_event_system_error_handling(self, browser_session):
		"""Test error handling in event system."""
		from browser_use.browser.events import BrowserStartEvent

		# Create session with invalid CDP URL to trigger error
		error_session = BrowserSession(
			browser_profile=BrowserProfile(headless=True),
			cdp_url='http://localhost:99999',  # Invalid port
		)

		try:
			# Dispatch start event directly - should trigger error handling
			start_event = error_session.event_bus.dispatch(BrowserStartEvent())

			# The event bus catches and logs the error, but the event awaits successfully
			await start_event

			# The session should not be initialized due to the error
			assert error_session._cdp_client_root is None, 'Session should not be initialized after connection error'

			# Verify the error was logged in the event history (good enough for error handling test)
			assert len(error_session.event_bus.event_history) > 0, 'Event should be tracked even with errors'

		finally:
			await error_session.kill()

	async def test_concurrent_event_dispatching(self, browser_session: BrowserSession):
		"""Test that concurrent events are handled properly."""
		from browser_use.browser.events import ScreenshotEvent

		# Start browser first
		await browser_session.start()

		# Dispatch multiple events concurrently
		screenshot_event1 = browser_session.event_bus.dispatch(ScreenshotEvent())
		screenshot_event2 = browser_session.event_bus.dispatch(ScreenshotEvent())

		# Both should complete successfully
		results = await asyncio.gather(screenshot_event1, screenshot_event2, return_exceptions=True)

		# Check that no exceptions were raised
		for result in results:
			assert not isinstance(result, Exception), f'Event failed with: {result}'

	# async def test_many_parallel_browser_sessions(self):
	# 	"""Test spawning 12 parallel browser_sessions with different settings and ensure they all work"""
	# 	from browser_use import BrowserSession

	# 	browser_sessions = []

	# 	for i in range(3):
	# 		browser_sessions.append(
	# 			BrowserSession(
	# 				browser_profile=BrowserProfile(
	# 					user_data_dir=None,
	# 					headless=True,
	# 					keep_alive=True,
	# 				),
	# 			)
	# 		)
	# 	for i in range(3):
	# 		browser_sessions.append(
	# 			BrowserSession(
	# 				browser_profile=BrowserProfile(
	# 					user_data_dir=Path(tempfile.mkdtemp(prefix=f'browseruse-tmp-{i}')),
	# 					headless=True,
	# 					keep_alive=True,
	# 				),
	# 			)
	# 		)
	# 	for i in range(3):
	# 		browser_sessions.append(
	# 			BrowserSession(
	# 				browser_profile=BrowserProfile(
	# 					user_data_dir=None,
	# 					headless=True,
	# 					keep_alive=False,
	# 				),
	# 			)
	# 		)
	# 	for i in range(3):
	# 		browser_sessions.append(
	# 			BrowserSession(
	# 				browser_profile=BrowserProfile(
	# 					user_data_dir=Path(tempfile.mkdtemp(prefix=f'browseruse-tmp-{i}')),
	# 					headless=True,
	# 					keep_alive=False,
	# 				),
	# 			)
	# 		)

	# 	print('Starting many parallel browser sessions...')
	# 	await asyncio.gather(*[browser_session.start() for browser_session in browser_sessions])

	# 	print('Ensuring all parallel browser sessions are connected and usable...')
	# 	new_tab_tasks = []
	# 	for browser_session in browser_sessions:
	# 		assert browser_session._cdp_client_root is not None
	# 		assert browser_session._cdp_client_root is not None
	# 		new_tab_tasks.append(browser_session.create_new_tab('chrome://version'))
	# 	await asyncio.gather(*new_tab_tasks)

	# 	print('killing every 3rd browser_session to test parallel shutdown')
	# 	kill_tasks = []
	# 	for i in range(0, len(browser_sessions), 3):
	# 		kill_tasks.append(browser_sessions[i].kill())
	# 		browser_sessions[i] = None
	# 	results = await asyncio.gather(*kill_tasks, return_exceptions=True)
	# 	# Check that no exceptions were raised during cleanup
	# 	for i, result in enumerate(results):
	# 		if isinstance(result, Exception):
	# 			print(f'Warning: Browser session kill raised exception: {type(result).__name__}: {result}')

	# 	print('ensuring the remaining browser_sessions are still connected and usable')
	# 	new_tab_tasks = []
	# 	screenshot_tasks = []
	# 	for browser_session in filter(bool, browser_sessions):
	# 		assert browser_session._cdp_client_root is not None
	# 		assert browser_session._cdp_client_root is not None
	# 		new_tab_tasks.append(browser_session.create_new_tab('chrome://version'))
	# 		screenshot_tasks.append(browser_session.take_screenshot())
	# 	await asyncio.gather(*new_tab_tasks)
	# 	await asyncio.gather(*screenshot_tasks)

	# 	kill_tasks = []
	# 	print('killing the remaining browser_sessions')
	# 	for browser_session in filter(bool, browser_sessions):
	# 		kill_tasks.append(browser_session.kill())
	# 	results = await asyncio.gather(*kill_tasks, return_exceptions=True)
	# 	# Check that no exceptions were raised during cleanup
	# 	for i, result in enumerate(results):
	# 		if isinstance(result, Exception):
	# 			print(f'Warning: Browser session kill raised exception: {type(result).__name__}: {result}')
