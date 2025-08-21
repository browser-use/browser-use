import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.controller.service import Controller
from browser_use.controller.views import GoToUrlAction


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

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
			
			<!-- Exactly like the HTML provided in the issue -->
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


class TestARIAMenuDropdown:
	"""Test ARIA menu support for get_dropdown_options and select_dropdown_option."""

	@pytest.mark.skip(reason='TODO: fix')
	async def test_get_dropdown_options_with_aria_menu(self, controller, browser_session: BrowserSession, base_url):
		"""Test that get_dropdown_options can retrieve options from ARIA menus."""
		# Navigate to the ARIA menu test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/aria-menu', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Wait for the page to load
		from browser_use.browser.events import NavigationCompleteEvent

		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Initialize the DOM state to populate the selector map
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map
		selector_map = await browser_session.get_selector_map()

		# Find the ARIA menu element in the selector map
		menu_index = None
		for idx, element in selector_map.items():
			# Look for the main UL with role="menu" and id="pyNavigation1752753375773"
			if (
				element.tag_name.lower() == 'ul'
				and element.attributes.get('role') == 'menu'
				and element.attributes.get('id') == 'pyNavigation1752753375773'
			):
				menu_index = idx
				break

		available_elements = [
			f'{idx}: {element.tag_name} id={element.attributes.get("id", "None")} role={element.attributes.get("role", "None")}'
			for idx, element in selector_map.items()
		]

		assert menu_index is not None, (
			f'Could not find ARIA menu element in selector map. Available elements: {available_elements}'
		)

		# Create a model for the get_dropdown_options action
		class GetDropdownOptionsModel(ActionModel):
			get_dropdown_options: dict[str, int]

		# Execute the action with the menu index
		result = await controller.act(
			action=GetDropdownOptionsModel(get_dropdown_options={'index': menu_index}),
			browser_session=browser_session,
		)

		# Verify the result structure
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Expected ARIA menu options
		expected_options = ['Filter', 'Sort', 'Appearance', 'Summarize', 'Delete']

		# Verify all options are returned
		for option in expected_options:
			assert option in result.extracted_content, f"Option '{option}' not found in result content"

		# Verify the instruction for using the text in select_dropdown_option is included
		assert 'Use the exact text string in select_dropdown_option' in result.extracted_content

	@pytest.mark.skip(reason='TODO: fix')
	async def test_select_dropdown_option_with_aria_menu(self, controller, browser_session: BrowserSession, base_url):
		"""Test that select_dropdown_option can select an option from ARIA menus."""
		# Navigate to the ARIA menu test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/aria-menu', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Wait for the page to load
		from browser_use.browser.events import NavigationCompleteEvent

		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Initialize the DOM state to populate the selector map
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map
		selector_map = await browser_session.get_selector_map()

		# Find the ARIA menu element in the selector map
		menu_index = None
		for idx, element in selector_map.items():
			# Look for the main UL with role="menu" and id="pyNavigation1752753375773"
			if (
				element.tag_name.lower() == 'ul'
				and element.attributes.get('role') == 'menu'
				and element.attributes.get('id') == 'pyNavigation1752753375773'
			):
				menu_index = idx
				break

		available_elements = [
			f'{idx}: {element.tag_name} id={element.attributes.get("id", "None")} role={element.attributes.get("role", "None")}'
			for idx, element in selector_map.items()
		]

		assert menu_index is not None, (
			f'Could not find ARIA menu element in selector map. Available elements: {available_elements}'
		)

		# Create a model for the select_dropdown_option action
		class SelectDropdownOptionModel(ActionModel):
			select_dropdown_option: dict

		# Execute the action with the menu index to select "Filter"
		result = await controller.act(
			SelectDropdownOptionModel(select_dropdown_option={'index': menu_index, 'text': 'Filter'}),
			browser_session,
		)

		# Verify the result structure
		assert isinstance(result, ActionResult)

		# Core logic validation: Verify selection was successful
		assert result.extracted_content is not None
		assert 'selected option' in result.extracted_content.lower() or 'clicked' in result.extracted_content.lower()
		assert 'Filter' in result.extracted_content

		# Verify the click actually had an effect on the page using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		result_text = result.get('result', {}).get('value', '')
		assert 'Filter' in result_text, f"Expected 'Filter' in result text, got '{result_text}'"

	@pytest.mark.skip(reason='TODO: fix')
	async def test_get_dropdown_options_with_nested_aria_menu(self, controller, browser_session: BrowserSession, base_url):
		"""Test that get_dropdown_options can handle nested ARIA menus (like Sort submenu)."""
		# Navigate to the ARIA menu test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/aria-menu', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Wait for the page to load
		from browser_use.browser.events import NavigationCompleteEvent

		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Initialize the DOM state to populate the selector map
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map
		selector_map = await browser_session.get_selector_map()

		# Find the nested ARIA menu element in the selector map
		nested_menu_index = None
		for idx, element in selector_map.items():
			# Look for the nested UL with id containing "$PpyNavigation"
			if (
				element.tag_name.lower() == 'ul'
				and '$PpyNavigation' in str(element.attributes.get('id', ''))
				and element.attributes.get('role') == 'menu'
			):
				nested_menu_index = idx
				break

		# The nested menu might not be in the selector map initially if it's hidden
		# In that case, we should test the main menu
		if nested_menu_index is None:
			# Find the main menu instead
			for idx, element in selector_map.items():
				if element.tag_name.lower() == 'ul' and element.attributes.get('id') == 'pyNavigation1752753375773':
					nested_menu_index = idx
					break

		assert nested_menu_index is not None, (
			f'Could not find any ARIA menu element in selector map. Available elements: {[f"{idx}: {element.tag_name}" for idx, element in selector_map.items()]}'
		)

		# Create a model for the get_dropdown_options action
		class GetDropdownOptionsModel(ActionModel):
			get_dropdown_options: dict[str, int]

		# Execute the action with the menu index
		result = await controller.act(
			action=GetDropdownOptionsModel(get_dropdown_options={'index': nested_menu_index}),
			browser_session=browser_session,
		)

		# Verify the result structure
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# The action should return some menu options
		assert 'Use the exact text string in select_dropdown_option' in result.extracted_content
