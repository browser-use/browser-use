"""Test GetDropdownOptionsEvent and SelectDropdownOptionEvent functionality.

This file consolidates all tests related to dropdown functionality including:
- Native <select> dropdowns
- ARIA role="menu" dropdowns
- Custom dropdown implementations
"""

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.events import GetDropdownOptionsEvent, NavigationCompleteEvent, SelectDropdownOptionEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.controller.service import Controller
from browser_use.controller.views import GoToUrlAction


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

	# Add route for native dropdown test page
	server.expect_request('/native-dropdown').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Native Dropdown Test</title>
		</head>
		<body>
			<h1>Native Dropdown Test</h1>
			<select id="test-dropdown" name="test-dropdown">
				<option value="">Please select</option>
				<option value="option1">First Option</option>
				<option value="option2">Second Option</option>
				<option value="option3">Third Option</option>
			</select>
			<div id="result">No selection made</div>
			<script>
				document.getElementById('test-dropdown').addEventListener('change', function(e) {
					document.getElementById('result').textContent = 'Selected: ' + e.target.options[e.target.selectedIndex].text;
				});
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Add route for ARIA menu test page
	server.expect_request('/aria-menu').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>ARIA Menu Test</title>
			<style>
				.menu {
					list-style: none;
					padding: 0;
					margin: 0;
					border: 1px solid #ccc;
					background: white;
					width: 200px;
				}
				.menu-item {
					padding: 10px 20px;
					border-bottom: 1px solid #eee;
				}
				.menu-item:hover {
					background: #f0f0f0;
				}
				.menu-item-anchor {
					text-decoration: none;
					color: #333;
					display: block;
				}
				#result {
					margin-top: 20px;
					padding: 10px;
					border: 1px solid #ddd;
					min-height: 20px;
				}
			</style>
		</head>
		<body>
			<h1>ARIA Menu Test</h1>
			<p>This menu uses ARIA roles instead of native select elements</p>
			
			<ul class="menu menu-format-standard menu-regular" role="menu" id="pyNavigation1752753375773" style="display: block;">
				<li class="menu-item menu-item-enabled" role="presentation">
					<a href="#" onclick="pd(event);" class="menu-item-anchor" tabindex="0" role="menuitem">
						<span class="menu-item-title-wrap"><span class="menu-item-title">Filter</span></span>
					</a>
				</li>
				<li class="menu-item menu-item-enabled" role="presentation" id="menu-item-$PpyNavigation1752753375773$ppyElements$l2">
					<a href="#" onclick="pd(event);" class="menu-item-anchor menu-item-expand" tabindex="0" role="menuitem" aria-haspopup="true">
						<span class="menu-item-title-wrap"><span class="menu-item-title">Sort</span></span>
					</a>
					<div class="menu-panel-wrapper">
						<ul class="menu menu-format-standard menu-regular" role="menu" id="$PpyNavigation1752753375773$ppyElements$l2">
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
				function pd(event) {
					event.preventDefault();
					const text = event.target.closest('[role="menuitem"]').textContent.trim();
					document.getElementById('result').textContent = 'Clicked: ' + text;
				}
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Add route for custom dropdown test page
	server.expect_request('/custom-dropdown').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Custom Dropdown Test</title>
			<style>
				.dropdown {
					position: relative;
					display: inline-block;
					width: 200px;
				}
				.dropdown-button {
					padding: 10px;
					border: 1px solid #ccc;
					background: white;
					cursor: pointer;
					width: 100%;
				}
				.dropdown-menu {
					position: absolute;
					top: 100%;
					left: 0;
					right: 0;
					border: 1px solid #ccc;
					background: white;
					display: block;
					z-index: 1000;
				}
				.dropdown-menu.hidden {
					display: none;
				}
				.dropdown .item {
					padding: 10px;
					cursor: pointer;
				}
				.dropdown .item:hover {
					background: #f0f0f0;
				}
				.dropdown .item.selected {
					background: #e0e0e0;
				}
				#result {
					margin-top: 20px;
					padding: 10px;
					border: 1px solid #ddd;
				}
			</style>
		</head>
		<body>
			<h1>Custom Dropdown Test</h1>
			<p>This is a custom dropdown implementation (like Semantic UI)</p>
			
			<div class="dropdown ui" id="custom-dropdown">
				<div class="dropdown-button" onclick="toggleDropdown()">
					<span id="selected-text">Choose an option</span>
				</div>
				<div class="dropdown-menu" id="dropdown-menu">
					<div class="item" data-value="red" onclick="selectOption('Red', 'red')">Red</div>
					<div class="item" data-value="green" onclick="selectOption('Green', 'green')">Green</div>
					<div class="item" data-value="blue" onclick="selectOption('Blue', 'blue')">Blue</div>
					<div class="item" data-value="yellow" onclick="selectOption('Yellow', 'yellow')">Yellow</div>
				</div>
			</div>
			
			<div id="result">No selection made</div>
			
			<script>
				function toggleDropdown() {
					const menu = document.getElementById('dropdown-menu');
					menu.classList.toggle('hidden');
				}
				
				function selectOption(text, value) {
					document.getElementById('selected-text').textContent = text;
					document.getElementById('result').textContent = 'Selected: ' + text + ' (value: ' + value + ')';
					// Mark as selected
					document.querySelectorAll('.item').forEach(item => item.classList.remove('selected'));
					event.target.classList.add('selected');
					// Close dropdown
					document.getElementById('dropdown-menu').classList.add('hidden');
				}
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

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
def controller():
	"""Create and provide a Controller instance."""
	return Controller()


class TestGetDropdownOptionsEvent:
	"""Test GetDropdownOptionsEvent functionality for various dropdown types."""

	async def test_native_select_dropdown(self, controller, browser_session: BrowserSession, base_url):
		"""Test get_dropdown_options with native HTML select element."""
		# Navigate to the native dropdown test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/native-dropdown', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Initialize the DOM state to populate the selector map
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map and find the select element
		selector_map = await browser_session.get_selector_map()
		dropdown_index = None
		for idx, element in selector_map.items():
			if element.tag_name.lower() == 'select' and element.attributes.get('id') == 'test-dropdown':
				dropdown_index = idx
				break

		assert dropdown_index is not None, (
			f'Could not find select element in selector map. Available elements: {[f"{idx}: {element.tag_name}" for idx, element in selector_map.items()]}'
		)

		# Test via controller action
		class GetDropdownOptionsModel(ActionModel):
			get_dropdown_options: dict[str, int]

		result = await controller.act(
			action=GetDropdownOptionsModel(get_dropdown_options={'index': dropdown_index}),
			browser_session=browser_session,
		)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Verify all expected options are present
		expected_options = ['Please select', 'First Option', 'Second Option', 'Third Option']
		for option in expected_options:
			assert option in result.extracted_content, f"Option '{option}' not found in result content"

		# Verify instruction is included
		assert 'Use the exact text string' in result.extracted_content and 'select_dropdown_option' in result.extracted_content

		# Also test direct event dispatch
		node = await browser_session.get_element_by_index(dropdown_index)
		assert node is not None
		event = browser_session.event_bus.dispatch(GetDropdownOptionsEvent(node=node))
		dropdown_data = await event.event_result(timeout=3.0)

		assert dropdown_data is not None
		assert 'options' in dropdown_data
		assert 'type' in dropdown_data
		assert dropdown_data['type'] == 'select'

	async def test_aria_menu_dropdown(self, controller, browser_session: BrowserSession, base_url):
		"""Test get_dropdown_options with ARIA role='menu' element."""
		# Navigate to the ARIA menu test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/aria-menu', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Initialize the DOM state
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map and find the ARIA menu
		selector_map = await browser_session.get_selector_map()
		menu_index = None
		for idx, element in selector_map.items():
			if (
				element.tag_name.lower() == 'ul'
				and element.attributes.get('role') == 'menu'
				and element.attributes.get('id') == 'pyNavigation1752753375773'
			):
				menu_index = idx
				break

		assert menu_index is not None, (
			f'Could not find ARIA menu element in selector map. Available elements: {[f"{idx}: {element.tag_name} role={element.attributes.get('role', 'None')}" for idx, element in selector_map.items()]}'
		)

		# Test via controller action
		class GetDropdownOptionsModel(ActionModel):
			get_dropdown_options: dict[str, int]

		result = await controller.act(
			action=GetDropdownOptionsModel(get_dropdown_options={'index': menu_index}),
			browser_session=browser_session,
		)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Verify expected ARIA menu options are present
		expected_options = ['Filter', 'Sort', 'Appearance', 'Summarize', 'Delete']
		for option in expected_options:
			assert option in result.extracted_content, f"Option '{option}' not found in result content"

		# Also test direct event dispatch
		node = await browser_session.get_element_by_index(menu_index)
		assert node is not None
		event = browser_session.event_bus.dispatch(GetDropdownOptionsEvent(node=node))
		dropdown_data = await event.event_result(timeout=3.0)

		assert dropdown_data is not None
		assert 'options' in dropdown_data
		assert 'type' in dropdown_data
		assert dropdown_data['type'] == 'aria'

	async def test_custom_dropdown(self, controller, browser_session: BrowserSession, base_url):
		"""Test get_dropdown_options with custom dropdown implementation."""
		# Navigate to the custom dropdown test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/custom-dropdown', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Initialize the DOM state
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map and find the custom dropdown
		selector_map = await browser_session.get_selector_map()
		dropdown_index = None
		for idx, element in selector_map.items():
			if element.attributes.get('id') == 'custom-dropdown' and 'dropdown' in element.attributes.get('class', ''):
				dropdown_index = idx
				break

		assert dropdown_index is not None, (
			f'Could not find custom dropdown element in selector map. Available elements: {[f"{idx}: {element.tag_name} id={element.attributes.get('id', 'None')}" for idx, element in selector_map.items()]}'
		)

		# Test via controller action
		class GetDropdownOptionsModel(ActionModel):
			get_dropdown_options: dict[str, int]

		result = await controller.act(
			action=GetDropdownOptionsModel(get_dropdown_options={'index': dropdown_index}),
			browser_session=browser_session,
		)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Verify expected custom dropdown options are present
		expected_options = ['Red', 'Green', 'Blue', 'Yellow']
		for option in expected_options:
			assert option in result.extracted_content, f"Option '{option}' not found in result content"

		# Also test direct event dispatch
		node = await browser_session.get_element_by_index(dropdown_index)
		assert node is not None
		event = browser_session.event_bus.dispatch(GetDropdownOptionsEvent(node=node))
		dropdown_data = await event.event_result(timeout=3.0)

		assert dropdown_data is not None
		assert 'options' in dropdown_data
		assert 'type' in dropdown_data
		assert dropdown_data['type'] == 'custom'

	async def test_element_not_found_error(self, controller, browser_session: BrowserSession, base_url):
		"""Test get_dropdown_options with invalid element index."""
		# Navigate to any test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/native-dropdown', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Try to get dropdown options with invalid index
		class GetDropdownOptionsModel(ActionModel):
			get_dropdown_options: dict[str, int]

		result = await controller.act(
			action=GetDropdownOptionsModel(get_dropdown_options={'index': 99999}),
			browser_session=browser_session,
		)

		# Should return an error
		assert isinstance(result, ActionResult)
		assert result.error is not None
		assert 'not found' in result.error.lower()


class TestSelectDropdownOptionEvent:
	"""Test SelectDropdownOptionEvent functionality for various dropdown types."""

	async def test_select_native_dropdown_option(self, controller, browser_session: BrowserSession, base_url):
		"""Test select_dropdown_option with native HTML select element."""
		# Navigate to the native dropdown test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/native-dropdown', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Initialize the DOM state
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map and find the select element
		selector_map = await browser_session.get_selector_map()
		dropdown_index = None
		for idx, element in selector_map.items():
			if element.tag_name.lower() == 'select' and element.attributes.get('id') == 'test-dropdown':
				dropdown_index = idx
				break

		assert dropdown_index is not None

		# Test via controller action
		class SelectDropdownOptionModel(ActionModel):
			select_dropdown_option: dict

		result = await controller.act(
			SelectDropdownOptionModel(select_dropdown_option={'index': dropdown_index, 'text': 'Second Option'}),
			browser_session,
		)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Second Option' in result.extracted_content

		# Verify the selection actually worked using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('test-dropdown').selectedIndex", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		selected_index = result.get('result', {}).get('value', -1)
		assert selected_index == 2, f'Expected selected index 2, got {selected_index}'

	async def test_select_aria_menu_option(self, controller, browser_session: BrowserSession, base_url):
		"""Test select_dropdown_option with ARIA menu."""
		# Navigate to the ARIA menu test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/aria-menu', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Initialize the DOM state
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map and find the ARIA menu
		selector_map = await browser_session.get_selector_map()
		menu_index = None
		for idx, element in selector_map.items():
			if (
				element.tag_name.lower() == 'ul'
				and element.attributes.get('role') == 'menu'
				and element.attributes.get('id') == 'pyNavigation1752753375773'
			):
				menu_index = idx
				break

		assert menu_index is not None

		# Test via controller action
		class SelectDropdownOptionModel(ActionModel):
			select_dropdown_option: dict

		result = await controller.act(
			SelectDropdownOptionModel(select_dropdown_option={'index': menu_index, 'text': 'Filter'}),
			browser_session,
		)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Filter' in result.extracted_content

		# Verify the click had an effect using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		result_text = result.get('result', {}).get('value', '')
		assert 'Filter' in result_text, f"Expected 'Filter' in result text, got '{result_text}'"

	async def test_select_custom_dropdown_option(self, controller, browser_session: BrowserSession, base_url):
		"""Test select_dropdown_option with custom dropdown."""
		# Navigate to the custom dropdown test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/custom-dropdown', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Initialize the DOM state
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map and find the custom dropdown
		selector_map = await browser_session.get_selector_map()
		dropdown_index = None
		for idx, element in selector_map.items():
			if element.attributes.get('id') == 'custom-dropdown' and 'dropdown' in element.attributes.get('class', ''):
				dropdown_index = idx
				break

		assert dropdown_index is not None

		# Test via controller action
		class SelectDropdownOptionModel(ActionModel):
			select_dropdown_option: dict

		result = await controller.act(
			SelectDropdownOptionModel(select_dropdown_option={'index': dropdown_index, 'text': 'Blue'}),
			browser_session,
		)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Blue' in result.extracted_content

		# Verify the selection worked using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		result_text = result.get('result', {}).get('value', '')
		assert 'Blue' in result_text, f"Expected 'Blue' in result text, got '{result_text}'"

	async def test_select_invalid_option_error(self, controller, browser_session: BrowserSession, base_url):
		"""Test select_dropdown_option with non-existent option text."""
		# Navigate to the native dropdown test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/native-dropdown', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Initialize the DOM state
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map and find the select element
		selector_map = await browser_session.get_selector_map()
		dropdown_index = None
		for idx, element in selector_map.items():
			if element.tag_name.lower() == 'select' and element.attributes.get('id') == 'test-dropdown':
				dropdown_index = idx
				break

		assert dropdown_index is not None

		# Try to select non-existent option via direct event
		node = await browser_session.get_element_by_index(dropdown_index)
		assert node is not None
		event = browser_session.event_bus.dispatch(SelectDropdownOptionEvent(node=node, text='Non-existent Option'))

		try:
			selection_data = await event.event_result(timeout=3.0)
			# Should have an error in the result
			assert selection_data is not None
			assert 'error' in selection_data or 'not found' in str(selection_data).lower()
		except Exception as e:
			# Or raise an exception
			assert 'not found' in str(e).lower() or 'no option' in str(e).lower()
