"""
Systematic debugging of the selector map issue.
Test each assumption step by step to isolate the problem.
"""

import os

import pytest

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.controller.service import Controller


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
			executable_path=os.getenv('BROWSER_PATH'),
			user_data_dir=None,  # Use temporary profile
			headless=True,
		)
	)
	async with session:
		yield session


@pytest.fixture
def controller():
	"""Create a controller instance."""
	return Controller()


@pytest.mark.asyncio
async def test_assumption_1_dom_processing_works(browser_session, httpserver):
	"""Test assumption 1: DOM processing works and finds elements."""
	# Go to a simple page
	page = await browser_session.get_current_page()
	await page.goto(httpserver.url_for('/'))
	await page.wait_for_load_state()

	# Trigger DOM processing
	state = await browser_session.get_state_summary(cache_clickable_elements_hashes=False)

	print('DOM processing result:')
	print(f'  - Elements found: {len(state.selector_map)}')
	print(f'  - Element indices: {list(state.selector_map.keys())}')

	# Verify DOM processing works
	assert len(state.selector_map) > 0, 'DOM processing should find elements'
	assert 0 in state.selector_map, 'Element index 0 should exist'


@pytest.mark.asyncio
async def test_assumption_2_cached_selector_map_persists(browser_session, httpserver):
	"""Test assumption 2: Cached selector map persists after get_state_summary."""
	# Go to a simple page
	page = await browser_session.get_current_page()
	await page.goto(httpserver.url_for('/'))
	await page.wait_for_load_state()

	# Trigger DOM processing and cache
	state = await browser_session.get_state_summary(cache_clickable_elements_hashes=False)
	initial_selector_map = dict(state.selector_map)

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
async def test_assumption_3_action_gets_same_selector_map(browser_session, controller, httpserver):
	"""Test assumption 3: Action gets the same selector map as cached."""
	# Go to a simple page
	page = await browser_session.get_current_page()
	await page.goto(httpserver.url_for('/'))
	await page.wait_for_load_state()

	# Trigger DOM processing and cache
	await browser_session.get_state_summary(cache_clickable_elements_hashes=False)
	cached_selector_map = await browser_session.get_selector_map()

	print('Pre-action state:')
	print(f'  - Cached elements: {len(cached_selector_map)}')
	print(f'  - Element 0 exists in cache: {0 in cached_selector_map}')

	# Create a test action that checks the selector map it receives
	@controller.registry.action('Test: Check selector map')
	async def test_check_selector_map(browser_session: BrowserSession):
		from browser_use import ActionResult

		action_selector_map = await browser_session.get_selector_map()
		return ActionResult(
			extracted_content=f'Action sees {len(action_selector_map)} elements, index 0 exists: {0 in action_selector_map}',
			include_in_memory=False,
		)

	# Execute the test action
	result = await controller.registry.execute_action('test_check_selector_map', {}, browser_session=browser_session)

	print(f'Action result: {result.extracted_content}')

	# Verify the action sees the same selector map
	assert 'index 0 exists: True' in result.extracted_content, 'Action should see element 0'


@pytest.mark.asyncio
async def test_assumption_4_click_action_specific_issue(browser_session, controller, httpserver):
	"""Test assumption 4: Specific issue with click_element_by_index action."""
	# Go to a simple page
	page = await browser_session.get_current_page()
	await page.goto(httpserver.url_for('/'))
	await page.wait_for_load_state()

	# Trigger DOM processing and cache
	await browser_session.get_state_summary(cache_clickable_elements_hashes=False)
	cached_selector_map = await browser_session.get_selector_map()

	print('Pre-click state:')
	print(f'  - Cached elements: {len(cached_selector_map)}')
	print(f'  - Element 0 exists: {0 in cached_selector_map}')

	# Create a test action that replicates click_element_by_index logic
	@controller.registry.action('Test: Debug click logic')
	async def test_debug_click_logic(index: int, browser_session: BrowserSession):
		from browser_use import ActionResult

		# This is the exact logic from click_element_by_index
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

	# Test with index 0
	result = await controller.registry.execute_action('test_debug_click_logic', {'index': 0}, browser_session=browser_session)

	print(f'Debug click result: {result.extracted_content or result.error}')

	# This will help us see exactly what the click action sees
	if result.error:
		pytest.fail(f'Click logic debug failed: {result.error}')


@pytest.mark.asyncio
async def test_assumption_5_multiple_get_selector_map_calls(browser_session, httpserver):
	"""Test assumption 5: Multiple calls to get_selector_map return consistent results."""
	# Go to a simple page
	page = await browser_session.get_current_page()
	await page.goto(httpserver.url_for('/'))
	await page.wait_for_load_state()

	# Trigger DOM processing and cache
	await browser_session.get_state_summary(cache_clickable_elements_hashes=False)

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


@pytest.mark.asyncio
async def test_assumption_6_page_changes_affect_selector_map(browser_session, httpserver):
	"""Test assumption 6: Check if page navigation affects cached selector map."""
	# Go to first page
	page = await browser_session.get_current_page()
	await page.goto(httpserver.url_for('/'))
	await page.wait_for_load_state()

	# Get initial selector map
	await browser_session.get_state_summary(cache_clickable_elements_hashes=False)
	initial_map = await browser_session.get_selector_map()

	print('Page change test:')
	print(f'  - Home page elements: {len(initial_map)}')

	# Navigate to a different page (without calling get_state_summary)
	await page.goto(httpserver.url_for('/page1'))
	await page.wait_for_load_state()

	# Check if cached selector map is still from old page
	cached_map_after_nav = await browser_session.get_selector_map()

	print(f'  - After navigation (cached): {len(cached_map_after_nav)}')
	print(f'  - Cache unchanged after nav: {len(initial_map) == len(cached_map_after_nav)}')

	# Update with new page
	await browser_session.get_state_summary(cache_clickable_elements_hashes=False)
	new_page_map = await browser_session.get_selector_map()

	print(f'  - Page 1 elements (fresh): {len(new_page_map)}')

	# This will tell us if cached maps get stale
	assert len(new_page_map) != len(initial_map) or initial_map.keys() != new_page_map.keys(), (
		'Different pages should have different selector maps'
	)


@pytest.mark.asyncio
async def test_assumption_8_same_browser_session_instance(browser_session, controller, httpserver):
	"""Test assumption 8: Action gets the same browser_session instance."""
	# Go to a simple page
	page = await browser_session.get_current_page()
	await page.goto(httpserver.url_for('/'))
	await page.wait_for_load_state()

	print('=== BROWSER SESSION INSTANCE DEBUG ===')

	# Get fresh state
	await browser_session.get_state_summary(cache_clickable_elements_hashes=False)

	# Store the ID of our browser session instance
	original_session_id = id(browser_session)
	print(f'1. Original browser_session ID: {original_session_id}')
	print(f'2. Original cache exists: {browser_session._cached_browser_state_summary is not None}')

	# Create action that checks browser session identity
	@controller.registry.action('Test: Check browser session identity')
	async def test_check_session_identity(browser_session: BrowserSession):
		from browser_use import ActionResult

		action_session_id = id(browser_session)
		cache_exists = browser_session._cached_browser_state_summary is not None
		return ActionResult(
			extracted_content=f'Action session ID: {action_session_id}, Cache exists: {cache_exists}', include_in_memory=False
		)

	# Execute action
	result = await controller.registry.execute_action('test_check_session_identity', {}, browser_session=browser_session)

	print(f'3. Action result: {result.extracted_content}')

	# Parse the result to check if session IDs match
	action_session_id = int(result.extracted_content.split('Action session ID: ')[1].split(',')[0])

	if original_session_id == action_session_id:
		print('✅ Same browser_session instance passed to action')
	else:
		print('❌ DIFFERENT browser_session instance passed to action!')
		print(f'   Original: {original_session_id}')
		print(f'   Action:   {action_session_id}')


@pytest.mark.asyncio
async def test_assumption_9_pydantic_private_attrs(browser_session, controller, httpserver):
	"""Test assumption 9: Pydantic model validation affects private attributes."""
	# Go to a simple page
	page = await browser_session.get_current_page()
	await page.goto(httpserver.url_for('/'))
	await page.wait_for_load_state()

	print('=== PYDANTIC PRIVATE ATTRS DEBUG ===')

	# Get fresh state
	await browser_session.get_state_summary(cache_clickable_elements_hashes=False)

	print(f'1. Original browser_session cache: {browser_session._cached_browser_state_summary is not None}')
	print(f'2. Original browser_session ID: {id(browser_session)}')

	# Import the SpecialActionParameters to test directly
	from browser_use.controller.registry.views import SpecialActionParameters

	# Test what happens when we put browser_session through model_validate
	special_params_data = {
		'context': None,
		'browser_session': browser_session,
		'browser': browser_session,
		'browser_context': browser_session,
		'page_extraction_llm': None,
		'available_file_paths': None,
		'has_sensitive_data': False,
	}

	print(f'3. Before model_validate - browser_session cache: {browser_session._cached_browser_state_summary is not None}')

	# Test the fixed version using model_construct instead of model_validate
	special_params = SpecialActionParameters.model_construct(**special_params_data)

	print(
		f'4. After model_validate - original browser_session cache: {browser_session._cached_browser_state_summary is not None}'
	)

	# Check the browser_session that comes out of the model
	extracted_browser_session = special_params.browser_session
	print(f'5. Extracted browser_session ID: {id(extracted_browser_session)}')
	print(f'6. Extracted browser_session cache: {extracted_browser_session._cached_browser_state_summary is not None}')

	# Check if they're the same object
	if id(browser_session) == id(extracted_browser_session):
		print('✅ Same object - no copying occurred')
	else:
		print('❌ DIFFERENT object - Pydantic copied the browser_session!')

		# Check if private attributes were preserved
		print(f'7. Original has _cached_browser_state_summary attr: {hasattr(browser_session, "_cached_browser_state_summary")}')
		print(
			f'8. Extracted has _cached_browser_state_summary attr: {hasattr(extracted_browser_session, "_cached_browser_state_summary")}'
		)

		if hasattr(extracted_browser_session, '_cached_browser_state_summary'):
			print(f'9. Extracted _cached_browser_state_summary value: {extracted_browser_session._cached_browser_state_summary}')


@pytest.mark.asyncio
async def test_assumption_7_cache_gets_cleared(browser_session, controller, httpserver):
	"""Test assumption 7: Check if _cached_browser_state_summary gets cleared."""
	# Go to a simple page
	page = await browser_session.get_current_page()
	await page.goto(httpserver.url_for('/'))
	await page.wait_for_load_state()

	print('=== CACHE CLEARING DEBUG ===')

	# Check initial cache state
	print(f'1. Initial cache state: {browser_session._cached_browser_state_summary}')

	# Get fresh state
	state = await browser_session.get_state_summary(cache_clickable_elements_hashes=False)
	print(f'2. After get_state_summary: cache exists = {browser_session._cached_browser_state_summary is not None}')
	print(f'3. Cache has {len(state.selector_map)} elements')

	# Check cache before action
	print(f'4. Pre-action cache: {browser_session._cached_browser_state_summary is not None}')

	# Create action that checks cache state (NO page parameter)
	@controller.registry.action('Test: Check cache state no page')
	async def test_check_cache_state_no_page(browser_session: BrowserSession):
		from browser_use import ActionResult

		cache_exists = browser_session._cached_browser_state_summary is not None
		if cache_exists:
			cache_size = len(browser_session._cached_browser_state_summary.selector_map)
		else:
			cache_size = 0
		return ActionResult(
			extracted_content=f'NoPage - Cache exists: {cache_exists}, Cache size: {cache_size}', include_in_memory=False
		)

	# Create action that checks cache state (WITH page parameter)
	@controller.registry.action('Test: Check cache state with page')
	async def test_check_cache_state_with_page(browser_session: BrowserSession, page):
		from browser_use import ActionResult

		cache_exists = browser_session._cached_browser_state_summary is not None
		if cache_exists:
			cache_size = len(browser_session._cached_browser_state_summary.selector_map)
		else:
			cache_size = 0
		return ActionResult(
			extracted_content=f'WithPage - Cache exists: {cache_exists}, Cache size: {cache_size}', include_in_memory=False
		)

	# Test action WITHOUT page parameter
	result_no_page = await controller.registry.execute_action(
		'test_check_cache_state_no_page', {}, browser_session=browser_session
	)

	print(f'5a. Action result (NO page): {result_no_page.extracted_content}')

	# Test action WITH page parameter
	result_with_page = await controller.registry.execute_action(
		'test_check_cache_state_with_page', {}, browser_session=browser_session
	)

	print(f'5b. Action result (WITH page): {result_with_page.extracted_content}')
	print(f'6. Post-action cache: {browser_session._cached_browser_state_summary is not None}')

	# This will tell us if the page parameter injection clears the cache


@pytest.mark.asyncio
async def test_final_real_click_with_debug(browser_session, controller, httpserver):
	"""Final test: Try actual click with maximum debugging."""
	# Go to a simple page
	page = await browser_session.get_current_page()
	await page.goto(httpserver.url_for('/'))
	await page.wait_for_load_state()

	print('=== FINAL CLICK TEST WITH FULL DEBUG ===')

	# Get fresh state
	state = await browser_session.get_state_summary(cache_clickable_elements_hashes=False)
	print(f'1. Fresh state has {len(state.selector_map)} elements')

	# Check cached map
	cached_map = await browser_session.get_selector_map()
	print(f'2. Cached map has {len(cached_map)} elements')
	print(f'3. Element 0 in cached map: {0 in cached_map}')

	# Try the real click action
	if 0 in cached_map:
		print('4. Attempting real click_element_by_index...')
		try:
			result = await controller.registry.execute_action(
				'click_element_by_index', {'index': 0}, browser_session=browser_session
			)
			print(f'5. Click SUCCESS: {result.extracted_content}')
		except Exception as e:
			print(f'5. Click FAILED: {e}')

			# Additional debug: check selector map inside the exception
			debug_map = await browser_session.get_selector_map()
			print(f'6. Post-failure selector map: {len(debug_map)} elements')
			print(f'7. Element 0 still in map: {0 in debug_map}')

			raise e
	else:
		pytest.fail('Element 0 not found in cached map - test setup issue')
