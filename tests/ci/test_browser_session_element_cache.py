"""
Systematic debugging of the selector map issue.
Test each assumption step by step to isolate the problem.
"""

import pytest

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools


@pytest.fixture
def httpserver(make_httpserver):
	"""Create and provide a test HTTP server that serves static content."""
	server = make_httpserver

	# Add routes for test pages
	server.expect_request('/').respond_with_data(
		"""<html>
		<head><title>Test Home Page</title></head>
		<body>
			<h1>Test Home Page</h1>
			<a href="/page1" id="link1">Link 1</a>
			<button id="button1">Button 1</button>
			<input type="text" id="input1" />
			<div id="div1" class="clickable">Clickable Div</div>
		</body>
		</html>""",
		content_type='text/html',
	)

	server.expect_request('/page1').respond_with_data(
		"""<html>
		<head><title>Test Page 1</title></head>
		<body>
			<h1>Test Page 1</h1>
			<p>This is test page 1</p>
			<a href="/">Back to home</a>
		</body>
		</html>""",
		content_type='text/html',
	)

	server.expect_request('/simple').respond_with_data(
		"""<html>
		<head><title>Simple Page</title></head>
		<body>
			<h1>Simple Page</h1>
			<p>This is a simple test page</p>
			<a href="/">Home</a>
		</body>
		</html>""",
		content_type='text/html',
	)

	return server


@pytest.fixture
async def browser_session():
	"""Create a real browser session for testing."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			user_data_dir=None,  # Use temporary profile
			headless=True,
		)
	)
	await session.start()
	yield session
	await session.stop()


@pytest.fixture
def tools():
	"""Create a tools instance."""
	return Tools()


@pytest.mark.asyncio
async def test_assumption_1_dom_processing_works(browser_session, httpserver):
	"""Test assumption 1: DOM processing works and finds elements."""
	# Go to a simple page using CDP events
	from browser_use.browser.events import NavigateToUrlEvent

	event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))
	await event
	await event.event_result(raise_if_any=True, raise_if_none=False)

	# Trigger DOM processing
	state = await browser_session.get_browser_state_summary()

	print('DOM processing result:')
	print(f'  - Elements found: {len(state.dom_state.selector_map)}')
	print(f'  - Element indices: {list(state.dom_state.selector_map.keys())}')

	# Verify DOM processing works
	assert len(state.dom_state.selector_map) > 0, 'DOM processing should find interactive elements'


@pytest.mark.asyncio
async def test_assumption_2_cached_selector_map_persists(browser_session, httpserver):
	"""Test assumption 2: Cached selector map persists after get_state_summary."""
	# Go to a simple page using CDP events
	from browser_use.browser.events import NavigateToUrlEvent

	event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))
	await event
	await event.event_result(raise_if_any=True, raise_if_none=False)

	# Trigger DOM processing and cache
	state = await browser_session.get_browser_state_summary()
	initial_selector_map = dict(state.dom_state.selector_map)

	# Check if cached selector map is still available
	cached_selector_map = await browser_session.get_selector_map()

	print('Selector map persistence:')
	print(f'  - Initial elements: {len(initial_selector_map)}')
	print(f'  - Cached elements: {len(cached_selector_map)}')
	print(f'  - Maps are identical: {initial_selector_map.keys() == cached_selector_map.keys()}')

	# Verify the cached map persists
	assert len(cached_selector_map) > 0, 'Cached selector map should persist'
	assert initial_selector_map.keys() == cached_selector_map.keys(), 'Cached map should match initial map'


@pytest.mark.asyncio
async def test_assumption_3_action_gets_same_selector_map(browser_session, tools, httpserver):
	"""Test assumption 3: Action gets the same selector map as cached."""
	# Go to a simple page using CDP events
	from browser_use.browser.events import NavigateToUrlEvent

	event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))
	await event
	await event.event_result(raise_if_any=True, raise_if_none=False)

	# Trigger DOM processing and cache
	await browser_session.get_browser_state_summary()
	cached_selector_map = await browser_session.get_selector_map()

	print('Pre-action state:')
	print(f'  - Cached elements: {len(cached_selector_map)}')
	print(f'  - Element 0 exists in cache: {0 in cached_selector_map}')

	# Create a test action that checks the selector map it receives
	@tools.registry.action('Test: Check selector map')
	async def test_check_selector_map(browser_session: BrowserSession):
		from browser_use import ActionResult

		action_selector_map = await browser_session.get_selector_map()
		return ActionResult(
			extracted_content=f'Action sees {len(action_selector_map)} elements, index 0 exists: {0 in action_selector_map}',
			include_in_memory=False,
		)

	# Execute the test action
	result = await tools.registry.execute_action('test_check_selector_map', {}, browser_session=browser_session)

	print(f'Action result: {result.extracted_content}')

	# Verify the action sees the same selector map
	assert 'index 0 exists: False' in result.extracted_content, 'Element 0 should not exist (elements start at 1)'


@pytest.mark.asyncio
async def test_assumption_4_click_action_specific_issue(browser_session, tools, httpserver):
	"""Test assumption 4: Specific issue with click action."""
	# Go to a simple page using CDP events
	from browser_use.browser.events import NavigateToUrlEvent

	event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))
	await event
	await event.event_result(raise_if_any=True, raise_if_none=False)

	# Trigger DOM processing and cache
	await browser_session.get_browser_state_summary()
	cached_selector_map = await browser_session.get_selector_map()

	print('Pre-click state:')
	print(f'  - Cached elements: {len(cached_selector_map)}')
	print(f'  - Element 0 exists: {0 in cached_selector_map}')

	# Create a test action that replicates click logic
	@tools.registry.action('Test: Debug click logic')
	async def test_debug_click_logic(index: int, browser_session: BrowserSession):
		from browser_use import ActionResult

		# This is the exact logic from click
		selector_map = await browser_session.get_selector_map()

		print(f'  - Action selector map size: {len(selector_map)}')
		print(f'  - Action selector map keys: {list(selector_map.keys())[:10]}')  # First 10
		print(f'  - Index {index} in selector map: {index in selector_map}')

		if index not in selector_map:
			return ActionResult(
				error=f'Debug: Element with index {index} does not exist in map of size {len(selector_map)}',
				include_in_memory=False,
			)

		return ActionResult(
			extracted_content=f'Debug: Element {index} found in map of size {len(selector_map)}', include_in_memory=False
		)

	# Test with index 1 (elements start at 1, not 0)
	result = await tools.registry.execute_action('test_debug_click_logic', {'index': 1}, browser_session=browser_session)

	print(f'Debug click result: {result.extracted_content or result.error}')

	# This will help us see exactly what the click action sees
	if result.error:
		pytest.fail(f'Click logic debug failed: {result.error}')


@pytest.mark.asyncio
async def test_assumption_5_multiple_get_selector_map_calls(browser_session, httpserver):
	"""Test assumption 5: Multiple calls to get_selector_map return consistent results."""
	# Go to a simple page using CDP events
	from browser_use.browser.events import NavigateToUrlEvent

	event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/')))
	await event
	await event.event_result(raise_if_any=True, raise_if_none=False)

	# Trigger DOM processing and cache
	await browser_session.get_browser_state_summary()

	# Call get_selector_map multiple times
	map1 = await browser_session.get_selector_map()
	map2 = await browser_session.get_selector_map()
	map3 = await browser_session.get_selector_map()

	print('Multiple selector map calls:')
	print(f'  - Call 1: {len(map1)} elements')
	print(f'  - Call 2: {len(map2)} elements')
	print(f'  - Call 3: {len(map3)} elements')
	print(f'  - All calls identical: {map1.keys() == map2.keys() == map3.keys()}')

	# Verify consistency
	assert len(map1) == len(map2) == len(map3), 'Multiple calls should return same size'
	assert map1.keys() == map2.keys() == map3.keys(), 'Multiple calls should return same elements'
