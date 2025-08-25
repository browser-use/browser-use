"""Test that search_google properly switches focus to the new tab."""

import asyncio

import pytest

from browser_use.browser import BrowserSession
from browser_use.browser.events import BrowserStateRequestEvent, NavigateToUrlEvent
from browser_use.controller.service import Controller


@pytest.fixture
async def browser_session():
	"""Create a browser session for testing."""
	session = BrowserSession()
	await session.start()
	yield session
	await session.stop()


async def test_search_google_creates_and_focuses_new_tab(browser_session: BrowserSession):
	"""Test that search_google creates a new tab and properly switches focus to it."""
	# Create controller to get the search_google action
	controller = Controller()

	# Get initial browser state
	initial_state_event = browser_session.event_bus.dispatch(BrowserStateRequestEvent(include_screenshot=False))
	initial_state = await initial_state_event
	initial_url = initial_state.url
	initial_tabs_count = len(initial_state.tabs)

	# Execute search_google action
	action_result = await controller.registry.execute_action(
		action_name='search_google',
		params={'query': 'test search'},
		browser_session=browser_session,
	)

	# Small delay to ensure navigation completes
	await asyncio.sleep(1)

	# Get browser state after search
	state_event = browser_session.event_bus.dispatch(BrowserStateRequestEvent(include_screenshot=False))
	state_after = await state_event

	# Verify a new tab was created
	assert len(state_after.tabs) == initial_tabs_count + 1, f'Expected {initial_tabs_count + 1} tabs, got {len(state_after.tabs)}'

	# Verify the current URL is Google search, not about:blank
	assert 'google.com/search' in state_after.url, f'Expected Google search URL, got {state_after.url}'
	assert state_after.url != initial_url, f"URL didn't change from {initial_url}"
	assert 'about:blank' not in state_after.url, 'Agent is still on about:blank after search_google'

	# Verify the search query is in the URL
	assert 'test+search' in state_after.url or 'test%20search' in state_after.url, f'Query not found in URL: {state_after.url}'

	print(f'✅ Test passed! Agent correctly focused on Google tab: {state_after.url}')


async def test_navigate_with_new_tab_focuses_properly(browser_session: BrowserSession):
	"""Test that NavigateToUrlEvent with new_tab=True properly switches focus."""
	# Get initial state
	initial_state_event = browser_session.event_bus.dispatch(BrowserStateRequestEvent(include_screenshot=False))
	initial_state = await initial_state_event
	initial_tabs_count = len(initial_state.tabs)

	# Navigate to a URL in a new tab
	nav_event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url='https://example.com', new_tab=True))
	await nav_event

	# Small delay to ensure navigation completes
	await asyncio.sleep(1)

	# Get browser state after navigation
	state_event = browser_session.event_bus.dispatch(BrowserStateRequestEvent(include_screenshot=False))
	state_after = await state_event

	# Verify a new tab was created
	assert len(state_after.tabs) == initial_tabs_count + 1, f'Expected {initial_tabs_count + 1} tabs, got {len(state_after.tabs)}'

	# Verify the current URL is the navigated URL
	assert 'example.com' in state_after.url, f'Expected example.com URL, got {state_after.url}'
	assert 'about:blank' not in state_after.url, 'Agent is still on about:blank after new tab navigation'

	print(f'✅ Test passed! Agent correctly focused on new tab: {state_after.url}')


async def test_multiple_new_tabs_focus_on_latest(browser_session: BrowserSession):
	"""Test that creating multiple new tabs focuses on the most recent one."""
	# Navigate to first new tab
	nav1_event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url='https://example.com', new_tab=True))
	await nav1_event
	await asyncio.sleep(0.5)

	# Navigate to second new tab
	nav2_event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url='https://github.com', new_tab=True))
	await nav2_event
	await asyncio.sleep(0.5)

	# Get browser state
	state_event = browser_session.event_bus.dispatch(BrowserStateRequestEvent(include_screenshot=False))
	state = await state_event

	# Should be focused on the most recent tab (github.com)
	assert 'github.com' in state.url, f'Expected github.com URL, got {state.url}'
	assert len(state.tabs) >= 3, f'Expected at least 3 tabs, got {len(state.tabs)}'

	print(f'✅ Test passed! Agent correctly focused on latest tab: {state.url}')


if __name__ == '__main__':
	# Run tests directly
	async def run_all_tests():
		session = BrowserSession()
		await session.start()
		try:
			print('Running test_search_google_creates_and_focuses_new_tab...')
			await test_search_google_creates_and_focuses_new_tab(session)

			print('\nRunning test_navigate_with_new_tab_focuses_properly...')
			await test_navigate_with_new_tab_focuses_properly(session)

			print('\nRunning test_multiple_new_tabs_focus_on_latest...')
			await test_multiple_new_tabs_focus_on_latest(session)

			print('\n✅ All tests passed!')
		finally:
			await session.stop()

	asyncio.run(run_all_tests())
