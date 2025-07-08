"""
Test the MCP server functionality with real browser sessions.

Tests cover:
- Navigation (current tab and new tab)
- Clicking elements (normal and new tab with modifiers)
- Typing text
- Getting browser state
- Content extraction
- Scrolling
- Tab management
- Browser session lifecycle
"""

import asyncio
import json

import pytest
from pytest_httpserver import HTTPServer

from browser_use.mcp.server import BrowserUseServer


class TestMCPServerNavigation:
	"""Test MCP server navigation functionality."""

	@pytest.fixture
	async def mcp_server_with_session(self):
		"""Create an MCP server with a real browser session."""
		server = BrowserUseServer()

		# Initialize browser session with the server's method
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		yield server

		# Cleanup
		if server.browser_session:
			await server.browser_session.kill()

	async def test_navigate_current_tab(self, mcp_server_with_session, httpserver: HTTPServer):
		"""Test navigation in current tab."""
		# Set up test page
		httpserver.expect_request('/test').respond_with_data('<h1>Test Page</h1>', content_type='text/html')
		test_url = httpserver.url_for('/test')

		# Navigate
		result = await mcp_server_with_session._navigate(test_url, new_tab=False)

		assert result == f'Navigated to: {test_url}'

		# Verify we're on the right page
		page = await mcp_server_with_session.browser_session.get_current_page()
		assert page.url == test_url

	async def test_navigate_new_tab(self, mcp_server_with_session, httpserver: HTTPServer):
		"""Test navigation in new tab."""
		# Set up test pages
		httpserver.expect_request('/page1').respond_with_data('<h1>Page 1</h1>', content_type='text/html')
		httpserver.expect_request('/page2').respond_with_data('<h1>Page 2</h1>', content_type='text/html')

		# Navigate to first page
		page1_url = httpserver.url_for('/page1')
		await mcp_server_with_session._navigate(page1_url, new_tab=False)

		# Navigate to second page in new tab
		page2_url = httpserver.url_for('/page2')
		result = await mcp_server_with_session._navigate(page2_url, new_tab=True)

		assert 'Opened new tab #1' in result
		assert page2_url in result

		# Verify we have 2 tabs
		assert len(mcp_server_with_session.browser_session.tabs) == 2

		# Verify current page is the new tab
		page = await mcp_server_with_session.browser_session.get_current_page()
		assert page.url == page2_url

	async def test_navigate_no_session(self):
		"""Test navigation without browser session."""
		server = BrowserUseServer()
		# Don't initialize session

		result = await server._navigate('https://example.com')
		assert result == 'Error: No browser session active'


class TestMCPServerClick:
	"""Test MCP server click functionality."""

	@pytest.fixture
	async def mcp_server_with_page(self, httpserver: HTTPServer):
		"""Create an MCP server with a test page loaded."""
		server = BrowserUseServer()
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		# Set up test page with clickable elements
		test_html = """
		<html>
			<body>
				<button id="btn1">Click Me</button>
				<a href="/linked-page" id="link1">Link to Page</a>
				<div id="div1" onclick="console.log('clicked')">Clickable Div</div>
				<input type="text" id="input1" placeholder="Type here">
			</body>
		</html>
		"""
		httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')
		httpserver.expect_request('/linked-page').respond_with_data('<h1>Linked Page</h1>', content_type='text/html')

		# Navigate to test page
		assert server.browser_session is not None
		await server.browser_session.navigate_to(httpserver.url_for('/test'))

		# Wait for page to load
		await asyncio.sleep(0.5)

		yield server

		# Cleanup
		assert server.browser_session is not None
		await server.browser_session.kill()

	async def test_click_normal(self, mcp_server_with_page):
		"""Test normal click on button."""
		# Get browser state to find button index
		assert mcp_server_with_page.browser_session is not None
		state = await mcp_server_with_page.browser_session.get_state_summary(cache_clickable_elements_hashes=False)

		# Find button index
		button_index = None
		for idx, elem in state.selector_map.items():
			if elem.tag_name == 'button':
				button_index = idx
				break

		assert button_index is not None, 'Button not found in selector map'

		# Click button
		result = await mcp_server_with_page._click(button_index, new_tab=False)
		assert result == f'Clicked element {button_index}'

	async def test_click_link_new_tab(self, mcp_server_with_page):
		"""Test click on link with new_tab=True."""
		# Get browser state to find link index
		state = await mcp_server_with_page.browser_session.get_state_summary(cache_clickable_elements_hashes=False)

		# Find link index
		link_index = None
		for idx, elem in state.selector_map.items():
			if elem.tag_name == 'a' and elem.attributes.get('href'):
				link_index = idx
				break

		assert link_index is not None, 'Link not found in selector map'

		# Click link in new tab
		result = await mcp_server_with_page._click(link_index, new_tab=True)

		assert 'opened in new tab' in result
		assert len(mcp_server_with_page.browser_session.tabs) == 2

	async def test_click_non_link_new_tab(self, mcp_server_with_page):
		"""Test click on non-link element with new_tab=True."""
		# Get browser state to find div index
		state = await mcp_server_with_page.browser_session.get_state_summary(cache_clickable_elements_hashes=False)

		# Find div index
		div_index = None
		for idx, elem in state.selector_map.items():
			if elem.tag_name == 'div' and elem.attributes.get('id') == 'div1':
				div_index = idx
				break

		assert div_index is not None, 'Div not found in selector map'

		# Click div with new tab modifier
		result = await mcp_server_with_page._click(div_index, new_tab=True)

		# Should use modifier key
		assert 'key (new tab if supported)' in result

	async def test_click_element_not_found(self, mcp_server_with_page):
		"""Test click when element is not found."""
		result = await mcp_server_with_page._click(9999)  # Non-existent index
		assert result == 'Element with index 9999 not found'

	async def test_click_no_session(self):
		"""Test click without browser session."""
		server = BrowserUseServer()
		result = await server._click(0)
		assert result == 'Error: No browser session active'


class TestMCPServerType:
	"""Test MCP server typing functionality."""

	@pytest.fixture
	async def mcp_server_with_input(self, httpserver: HTTPServer):
		"""Create an MCP server with a test page containing input field."""
		server = BrowserUseServer()
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		# Set up test page
		test_html = """
		<html>
			<body>
				<input type="text" id="input1" placeholder="Type here">
				<textarea id="textarea1" placeholder="Enter text"></textarea>
			</body>
		</html>
		"""
		httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')

		# Navigate to test page
		assert server.browser_session is not None
		await server.browser_session.navigate_to(httpserver.url_for('/test'))
		await asyncio.sleep(0.5)

		yield server

		# Cleanup
		assert server.browser_session is not None
		await server.browser_session.kill()

	async def test_type_text_in_input(self, mcp_server_with_input):
		"""Test typing text into input field."""
		# Get browser state to find input index
		state = await mcp_server_with_input.browser_session.get_state_summary(cache_clickable_elements_hashes=False)

		# Find input index
		input_index = None
		for idx, elem in state.selector_map.items():
			if elem.tag_name == 'input':
				input_index = idx
				break

		assert input_index is not None, 'Input not found in selector map'

		# Type text
		test_text = 'Hello MCP Server!'
		result = await mcp_server_with_input._type_text(input_index, test_text)

		assert result == f"Typed '{test_text}' into element {input_index}"

		# Verify text was typed
		page = await mcp_server_with_input.browser_session.get_current_page()
		value = await page.locator('#input1').input_value()
		assert value == test_text

	async def test_type_element_not_found(self, mcp_server_with_input):
		"""Test typing when element is not found."""
		result = await mcp_server_with_input._type_text(9999, 'test')
		assert result == 'Element with index 9999 not found'

	async def test_type_no_session(self):
		"""Test typing without browser session."""
		server = BrowserUseServer()
		result = await server._type_text(0, 'test')
		assert result == 'Error: No browser session active'


class TestMCPServerState:
	"""Test MCP server browser state functionality."""

	@pytest.fixture
	async def mcp_server_with_complex_page(self, httpserver: HTTPServer):
		"""Create an MCP server with a complex test page."""
		server = BrowserUseServer()
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		# Set up test page
		test_html = """
		<html>
			<head><title>Test Page Title</title></head>
			<body>
				<h1>Test Page</h1>
				<button>Button 1</button>
				<a href="/page2">Link 1</a>
				<input type="text" placeholder="Input field">
				<select>
					<option>Option 1</option>
					<option>Option 2</option>
				</select>
			</body>
		</html>
		"""
		httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')

		# Navigate to test page
		assert server.browser_session is not None
		await server.browser_session.navigate_to(httpserver.url_for('/test'))
		await asyncio.sleep(0.5)

		yield server

		# Cleanup
		assert server.browser_session is not None
		await server.browser_session.kill()

	async def test_get_browser_state(self, mcp_server_with_complex_page):
		"""Test getting browser state."""
		result = await mcp_server_with_complex_page._get_browser_state(include_screenshot=False)

		# Parse result
		state_data = json.loads(result)

		# Verify state structure
		assert 'url' in state_data
		assert 'title' in state_data
		assert state_data['title'] == 'Test Page Title'
		assert 'tabs' in state_data
		assert 'interactive_elements' in state_data

		# Verify we have interactive elements
		assert len(state_data['interactive_elements']) > 0

		# Check element structure
		first_elem = state_data['interactive_elements'][0]
		assert 'index' in first_elem
		assert 'tag' in first_elem
		assert 'text' in first_elem

	async def test_get_browser_state_no_session(self):
		"""Test getting state without browser session."""
		server = BrowserUseServer()
		result = await server._get_browser_state()
		assert result == 'Error: No browser session active'


class TestMCPServerScroll:
	"""Test MCP server scrolling functionality."""

	@pytest.fixture
	async def mcp_server_with_scrollable_page(self, httpserver: HTTPServer):
		"""Create an MCP server with a scrollable test page."""
		server = BrowserUseServer()
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		# Set up scrollable test page
		test_html = """
		<html>
			<body style="height: 3000px;">
				<h1>Top of Page</h1>
				<div style="margin-top: 1500px;">
					<h2>Middle of Page</h2>
				</div>
				<div style="margin-top: 1000px;">
					<h2>Bottom of Page</h2>
				</div>
			</body>
		</html>
		"""
		httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')

		# Navigate to test page
		assert server.browser_session is not None
		await server.browser_session.navigate_to(httpserver.url_for('/test'))
		await asyncio.sleep(0.5)

		yield server

		# Cleanup
		assert server.browser_session is not None
		await server.browser_session.kill()

	async def test_scroll_down(self, mcp_server_with_scrollable_page):
		"""Test scrolling down."""
		# Get initial scroll position
		page = await mcp_server_with_scrollable_page.browser_session.get_current_page()
		initial_scroll = await page.evaluate('() => window.pageYOffset')

		# Scroll down
		result = await mcp_server_with_scrollable_page._scroll(direction='down')
		assert result == 'Scrolled down'

		# Verify scroll position changed
		new_scroll = await page.evaluate('() => window.pageYOffset')
		assert new_scroll > initial_scroll

	async def test_scroll_up(self, mcp_server_with_scrollable_page):
		"""Test scrolling up."""
		page = await mcp_server_with_scrollable_page.browser_session.get_current_page()

		# First scroll down
		await mcp_server_with_scrollable_page._scroll(direction='down')
		down_scroll = await page.evaluate('() => window.pageYOffset')

		# Then scroll up
		result = await mcp_server_with_scrollable_page._scroll(direction='up')
		assert result == 'Scrolled up'

		# Verify scroll position changed
		up_scroll = await page.evaluate('() => window.pageYOffset')
		assert up_scroll < down_scroll

	async def test_scroll_no_session(self):
		"""Test scrolling without browser session."""
		server = BrowserUseServer()
		result = await server._scroll()
		assert result == 'Error: No browser session active'


class TestMCPServerTabManagement:
	"""Test MCP server tab management functionality."""

	@pytest.fixture
	async def mcp_server_with_tabs(self, httpserver: HTTPServer):
		"""Create an MCP server with multiple tabs."""
		server = BrowserUseServer()
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		# Set up test pages
		httpserver.expect_request('/tab1').respond_with_data('<h1>Tab 1</h1>', content_type='text/html')
		httpserver.expect_request('/tab2').respond_with_data('<h1>Tab 2</h1>', content_type='text/html')
		httpserver.expect_request('/tab3').respond_with_data('<h1>Tab 3</h1>', content_type='text/html')

		# Open multiple tabs
		assert server.browser_session is not None
		await server.browser_session.navigate_to(httpserver.url_for('/tab1'))
		await server.browser_session.create_new_tab(httpserver.url_for('/tab2'))
		await server.browser_session.create_new_tab(httpserver.url_for('/tab3'))

		yield server

		# Cleanup
		assert server.browser_session is not None
		await server.browser_session.kill()

	async def test_list_tabs(self, mcp_server_with_tabs):
		"""Test listing tabs."""
		result = await mcp_server_with_tabs._list_tabs()

		# Parse result
		tabs = json.loads(result)

		assert len(tabs) == 3
		for i, tab in enumerate(tabs):
			assert tab['index'] == i
			assert 'url' in tab
			assert 'title' in tab
			assert f'/tab{i + 1}' in tab['url']

	async def test_switch_tab(self, mcp_server_with_tabs):
		"""Test switching tabs."""
		# Switch to first tab
		result = await mcp_server_with_tabs._switch_tab(0)

		assert 'Switched to tab 0' in result
		assert '/tab1' in result

		# Verify current tab
		page = await mcp_server_with_tabs.browser_session.get_current_page()
		assert '/tab1' in page.url

	async def test_close_tab(self, mcp_server_with_tabs):
		"""Test closing a tab."""
		# Close middle tab
		result = await mcp_server_with_tabs._close_tab(1)

		assert 'Closed tab 1' in result
		assert '/tab2' in result

		# Verify tab count
		assert len(mcp_server_with_tabs.browser_session.tabs) == 2

	async def test_close_tab_invalid_index(self, mcp_server_with_tabs):
		"""Test closing tab with invalid index."""
		result = await mcp_server_with_tabs._close_tab(10)
		assert result == 'Invalid tab index: 10'

	async def test_tab_operations_no_session(self):
		"""Test tab operations without browser session."""
		server = BrowserUseServer()

		assert await server._list_tabs() == 'Error: No browser session active'
		assert await server._switch_tab(0) == 'Error: No browser session active'
		assert await server._close_tab(0) == 'Error: No browser session active'


class TestMCPServerHistory:
	"""Test MCP server browser history navigation."""

	@pytest.fixture
	async def mcp_server_with_history(self, httpserver: HTTPServer):
		"""Create an MCP server with navigation history."""
		server = BrowserUseServer()
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		# Set up test pages
		httpserver.expect_request('/page1').respond_with_data('<h1>Page 1</h1>', content_type='text/html')
		httpserver.expect_request('/page2').respond_with_data('<h1>Page 2</h1>', content_type='text/html')

		# Navigate to create history
		assert server.browser_session is not None
		await server.browser_session.navigate_to(httpserver.url_for('/page1'))
		await server.browser_session.navigate_to(httpserver.url_for('/page2'))

		yield server

		# Cleanup
		assert server.browser_session is not None
		await server.browser_session.kill()

	async def test_go_back(self, mcp_server_with_history):
		"""Test going back in history."""
		# Verify we're on page2
		page = await mcp_server_with_history.browser_session.get_current_page()
		assert '/page2' in page.url

		# Go back
		result = await mcp_server_with_history._go_back()
		assert result == 'Navigated back'

		# Verify we're on page1
		page = await mcp_server_with_history.browser_session.get_current_page()
		assert '/page1' in page.url

	async def test_go_back_no_session(self):
		"""Test going back without browser session."""
		server = BrowserUseServer()
		result = await server._go_back()
		assert result == 'Error: No browser session active'


class TestMCPServerExtraction:
	"""Test MCP server content extraction functionality."""

	@pytest.fixture
	async def mcp_server_with_content(self, httpserver: HTTPServer, mock_llm):
		"""Create an MCP server with content to extract."""
		server = BrowserUseServer()
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		# Set up the mock LLM for extraction
		server.llm = mock_llm

		# Set up test page with content
		test_html = """
		<html>
			<body>
				<h1>Product Page</h1>
				<div class="product">
					<h2>Amazing Widget</h2>
					<p class="price">$99.99</p>
					<p class="description">This is an amazing widget that does amazing things.</p>
					<a href="/buy">Buy Now</a>
				</div>
			</body>
		</html>
		"""
		httpserver.expect_request('/test').respond_with_data(test_html, content_type='text/html')

		# Navigate to test page
		assert server.browser_session is not None
		await server.browser_session.navigate_to(httpserver.url_for('/test'))
		await asyncio.sleep(0.5)

		yield server

		# Cleanup
		assert server.browser_session is not None
		await server.browser_session.kill()

	async def test_extract_content_no_llm(self):
		"""Test extraction without LLM."""
		server = BrowserUseServer()
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)
		server.llm = None

		result = await server._extract_content('query')
		assert result == 'Error: LLM not initialized (set OPENAI_API_KEY)'

	async def test_extract_content_no_filesystem(self, mock_llm):
		"""Test extraction without filesystem."""
		server = BrowserUseServer()
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)
		server.llm = mock_llm  # Use the mock from conftest
		server.file_system = None

		result = await server._extract_content('query')
		assert result == 'Error: FileSystem not initialized'

	async def test_extract_content_no_controller(self, mock_llm):
		"""Test extraction without controller."""
		server = BrowserUseServer()
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)
		server.llm = mock_llm  # Use mock LLM so we get past the LLM check
		server.controller = None

		result = await server._extract_content('query')
		assert result == 'Error: Controller not initialized'

	async def test_extract_content_no_session(self):
		"""Test extraction without browser session."""
		server = BrowserUseServer()
		# Don't set LLM since that check comes first
		# server.llm = None
		# server.file_system = None

		result = await server._extract_content('query')
		assert result == 'Error: LLM not initialized (set OPENAI_API_KEY)'


class TestMCPServerLifecycle:
	"""Test MCP server lifecycle operations."""

	async def test_init_browser_session(self):
		"""Test browser session initialization."""
		server = BrowserUseServer()

		# Verify no session initially
		assert server.browser_session is None
		assert server.controller is None
		assert server.file_system is None

		# Initialize session
		await server._init_browser_session(allowed_domains=['example.com'], headless=True, user_data_dir=None, keep_alive=False)

		# Verify all components initialized
		assert server.browser_session is not None
		assert server.controller is not None
		assert server.file_system is not None

		# Verify browser profile settings
		assert server.browser_session is not None
		assert server.browser_session.browser_profile.allowed_domains == ['example.com']

		# Cleanup
		assert server.browser_session is not None
		await server.browser_session.kill()  # type: ignore[reportGeneralTypeIssues]

	async def test_init_browser_session_already_exists(self):
		"""Test that browser session is not recreated if it already exists."""
		server = BrowserUseServer()

		# Initialize first session
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)
		first_session = server.browser_session

		# Try to initialize again
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		# Should be the same session
		assert server.browser_session is first_session

		# Cleanup
		assert server.browser_session is not None
		await server.browser_session.kill()

	async def test_close_browser(self):
		"""Test closing browser session."""
		server = BrowserUseServer()

		# Initialize session
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		# Close browser
		result = await server._close_browser()
		assert result == 'Browser closed'

		# Verify everything cleaned up
		assert server.browser_session is None
		assert server.controller is None

	async def test_close_browser_no_session(self):
		"""Test closing when no browser session."""
		server = BrowserUseServer()

		result = await server._close_browser()
		assert result == 'No browser session to close'


class TestMCPServerWithLLM:
	"""Test MCP server with LLM functionality."""

	async def test_init_with_mock_llm(self, mock_llm):
		"""Test initialization with mock LLM."""
		server = BrowserUseServer()

		# Initialize browser session
		await server._init_browser_session(headless=True, user_data_dir=None, keep_alive=False)

		# Manually set the mock LLM since we're not using real API key
		server.llm = mock_llm

		# Verify LLM is set
		assert server.llm is not None

		# Cleanup
		assert server.browser_session is not None
		await server.browser_session.kill()


if __name__ == '__main__':
	pytest.main([__file__, '-v', '-s'])
