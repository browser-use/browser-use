import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools

# Test fixture menu element ID used in HTML fixture
TEST_MENU_ID = 'pyNavigation1752753375773'

# Retry configuration constants
MAX_DOCUMENT_READY_ATTEMPTS = 10
MAX_MENU_DETECTION_ATTEMPTS = 20
RETRY_INTERVAL_SECONDS = 0.1


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

	# Build HTML with TEST_MENU_ID interpolated for single source of truth
	aria_menu_html = f"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>ARIA Menu Test</title>
			<style>
				.menu {{
					list-style: none;
					padding: 0;
					margin: 0;
					border: 1px solid #ccc;
					background: white;
					width: 200px;
				}}
				.menu-item {{
					padding: 10px 20px;
					border-bottom: 1px solid #eee;
				}}
				.menu-item:hover {{
					background: #f0f0f0;
				}}
				.menu-item-anchor {{
					text-decoration: none;
					color: #333;
					display: block;
				}}
				#result {{
					margin-top: 20px;
					padding: 10px;
					border: 1px solid #ddd;
					min-height: 20px;
				}}
			</style>
		</head>
		<body>
			<h1>ARIA Menu Test</h1>
			<p>This menu uses ARIA roles instead of native select elements</p>
			
			<!-- Exactly like the HTML provided in the issue -->
			<!-- Add tabindex to make menu focusable and detectable by selector map -->
			<ul class="menu menu-format-standard menu-regular" role="menu" id="{TEST_MENU_ID}" tabindex="0" style="display: block;">
				<li class="menu-item menu-item-enabled" role="presentation">
					<a href="#" onclick="pd(event);" class="menu-item-anchor" tabindex="0" role="menuitem">
						<span class="menu-item-title-wrap"><span class="menu-item-title">Filter</span></span>
					</a>
				</li>
				<li class="menu-item menu-item-enabled" role="presentation" id="menu-item-$P{TEST_MENU_ID}$ppyElements$l2">
					<a href="#" onclick="pd(event);" class="menu-item-anchor menu-item-expand" tabindex="0" role="menuitem" aria-haspopup="true">
						<span class="menu-item-title-wrap"><span class="menu-item-title">Sort</span></span>
					</a>
					<div class="menu-panel-wrapper">
						<ul class="menu menu-format-standard menu-regular" role="menu" id="$P{TEST_MENU_ID}$ppyElements$l2" tabindex="0">
							<li class="menu-item menu-item-enabled" role="presentation">
								<a href="#" onclick="pd(event);" class="menu-item-anchor" tabindex="0" role="menuitem">
									<span class="menu-item-title-wrap"><span class="menu-item-title">Lowest to highest</span></span>
								</a>
							</li>
							<li class="menu-item menu-item-enabled" role="presentation">
								<a href="#" onclick="pd(event);" class="menu-item-anchor" tabindex="0" role="menuitem">
									<span class="menu-item-title-wrap"><span class="menu-item-title">Highest to lowest</span></span>
								</a>
							</li>
						</ul>
					</div>
				</li>
				<li class="menu-item menu-item-enabled" role="presentation">
					<a href="#" onclick="pd(event);" class="menu-item-anchor" tabindex="0" role="menuitem">
						<span class="menu-item-title-wrap"><span class="menu-item-title">Appearance</span></span>
					</a>
				</li>
				<li class="menu-item menu-item-enabled" role="presentation">
					<a href="#" onclick="pd(event);" class="menu-item-anchor" tabindex="0" role="menuitem">
						<span class="menu-item-title-wrap"><span class="menu-item-title">Summarize</span></span>
					</a>
				</li>
				<li class="menu-item menu-item-enabled" role="presentation">
					<a href="#" onclick="pd(event);" class="menu-item-anchor" tabindex="0" role="menuitem">
						<span class="menu-item-title-wrap"><span class="menu-item-title">Delete</span></span>
					</a>
				</li>
			</ul>
			
			<div id="result">Click an option to see the result</div>
			
			<script>
				// Mock the pd function that prevents default
				function pd(event) {{
					event.preventDefault();
					const text = event.target.closest('[role="menuitem"]').textContent.trim();
					document.getElementById('result').textContent = 'Clicked: ' + text;
				}}
			</script>
		</body>
		</html>
		"""

	# Add route for ARIA menu test page
	server.expect_request('/aria-menu').respond_with_data(aria_menu_html, content_type='text/html')

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	"""Create and provide a Browser instance with security disabled."""
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			chromium_sandbox=False,  # Disable sandbox for CI environment
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.kill()


@pytest.fixture(scope='function')
def tools():
	"""Create and provide a Tools instance."""
	return Tools()


async def _wait_for_menu_element(browser_session: BrowserSession, menu_id: str) -> int:
	"""Wait for ARIA menu element to be available in selector map and return its index.

	Args:
		browser_session: The browser session to use
		menu_id: The ID of the menu element to find

	Returns:
		The index of the menu element in the selector map

	Raises:
		AssertionError: If the document never becomes ready or the menu element is not found
	"""
	# Wait for document to be ready using CDP
	cdp_session = await browser_session.get_or_create_cdp_session()

	# Wait for document ready state instead of hardcoded sleep
	document_ready = False
	for attempt in range(MAX_DOCUMENT_READY_ATTEMPTS):
		ready_state = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.readyState', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		if ready_state.get('result', {}).get('value') == 'complete':
			document_ready = True
			break
		await asyncio.sleep(RETRY_INTERVAL_SECONDS)

	# Fail deterministically if the document never reaches the complete state
	assert document_ready, 'Timed out waiting for document.readyState == "complete"'

	# Retry until the ARIA menu element is available in the selector map
	menu_index = None
	for _ in range(MAX_MENU_DETECTION_ATTEMPTS):
		# Initialize or refresh the DOM state to populate the selector map without taking screenshots
		await browser_session.get_browser_state_summary(include_screenshot=False)
		# Attempt to find the ARIA menu element by ID
		menu_index = await browser_session.get_index_by_id(menu_id)
		if menu_index is not None:
			break
		# Allow some time for the element/selector map to become available
		await asyncio.sleep(RETRY_INTERVAL_SECONDS)

	assert menu_index is not None, (
		f'Could not find ARIA menu element with id="{menu_id}" after {MAX_MENU_DETECTION_ATTEMPTS} attempts'
	)
	return menu_index


class TestARIAMenuDropdown:
	"""Test ARIA menu support for get_dropdown_options and select_dropdown_option."""

	async def test_get_dropdown_options_with_aria_menu(self, tools, browser_session: BrowserSession, base_url):
		"""Test that get_dropdown_options can retrieve options from ARIA menus."""
		# Navigate to the ARIA menu test page
		await tools.navigate(url=f'{base_url}/aria-menu', new_tab=False, browser_session=browser_session)

		# Wait for menu element to be available in selector map
		menu_index = await _wait_for_menu_element(browser_session, TEST_MENU_ID)

		# Execute the action with the menu index
		result = await tools.dropdown_options(index=menu_index, browser_session=browser_session)

		# Verify the result structure
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Expected ARIA menu options
		expected_options = ['Filter', 'Sort', 'Appearance', 'Summarize', 'Delete']

		# Verify all options are returned
		for option in expected_options:
			assert option in result.extracted_content, f"Option '{option}' not found in result content"

		# Verify the instruction for using the text in select_dropdown is included
		assert 'Use the exact text' in result.extracted_content and 'select_dropdown' in result.extracted_content

	async def test_select_dropdown_option_with_aria_menu(self, tools, browser_session: BrowserSession, base_url):
		"""Test that select_dropdown_option can select an option from ARIA menus."""
		# Navigate to the ARIA menu test page
		await tools.navigate(url=f'{base_url}/aria-menu', new_tab=False, browser_session=browser_session)

		# Wait for menu element to be available in selector map
		menu_index = await _wait_for_menu_element(browser_session, TEST_MENU_ID)

		# Execute the action with the menu index to select "Filter"
		result = await tools.select_dropdown(index=menu_index, text='Filter', browser_session=browser_session)

		# Verify the result structure
		assert isinstance(result, ActionResult)

		# Core logic validation: Verify selection was successful
		assert result.extracted_content is not None
		assert 'selected' in result.extracted_content.lower() or 'clicked' in result.extracted_content.lower()
		assert 'Filter' in result.extracted_content

		# Verify the click actually had an effect on the page using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		result_text = result.get('result', {}).get('value', '')
		assert 'Filter' in result_text, f"Expected 'Filter' in result text, got '{result_text}'"

	async def test_get_dropdown_options_with_nested_aria_menu(self, tools, browser_session: BrowserSession, base_url):
		"""Test that get_dropdown_options can handle nested ARIA menus (like Sort submenu)."""
		# Navigate to the ARIA menu test page
		await tools.navigate(url=f'{base_url}/aria-menu', new_tab=False, browser_session=browser_session)

		# Wait for menu element to be available in selector map
		await _wait_for_menu_element(browser_session, TEST_MENU_ID)

		# Get the selector map
		selector_map = await browser_session.get_selector_map()

		# Find the nested ARIA menu element in the selector map
		nested_menu_index = None
		nested_menu_id = f'$P{TEST_MENU_ID}$ppyElements$l2'
		for idx, element in selector_map.items():
			# Look for the nested UL with the specific nested menu ID
			if (
				element.tag_name.lower() == 'ul'
				and element.attributes.get('id') == nested_menu_id
				and element.attributes.get('role') == 'menu'
			):
				nested_menu_index = idx
				break

		# Assert that the nested menu was actually found (not just fall back to main menu)
		available_elements = [
			f'{idx}: {element.tag_name} (id={element.attributes.get("id", "none")})' for idx, element in selector_map.items()
		]
		assert nested_menu_index is not None, (
			f'Could not find nested ARIA menu element with id="{nested_menu_id}" in selector map. '
			f'Available elements: {available_elements}'
		)

		# Execute the action with the menu index
		result = await tools.dropdown_options(index=nested_menu_index, browser_session=browser_session)

		# Verify the result structure
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# The action should return some menu options
		assert 'Use the exact text' in result.extracted_content and 'select_dropdown' in result.extracted_content
