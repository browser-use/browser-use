import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig


class TestBrowserFunctionality:
	"""Integration tests for Browser functionality using a local HTTP server."""

	@pytest.fixture(scope='module')
	def event_loop(self):
		"""Create and provide an event loop for async tests."""
		loop = asyncio.get_event_loop_policy().new_event_loop()
		yield loop
		loop.close()

	@pytest.fixture(scope='module')
	def http_server(self):
		"""Create and provide a test HTTP server that serves static content."""
		server = HTTPServer()
		server.start()

		# Add routes for test pages
		server.expect_request('/').respond_with_data(
			'<html><head><title>Test Home Page</title></head><body><h1>Test Home Page</h1><p>Welcome to the test site</p></body></html>',
			content_type='text/html',
		)

		server.expect_request('/page1').respond_with_data(
			'<html><head><title>Test Page 1</title></head><body><h1>Test Page 1</h1><p>This is test page 1</p></body></html>',
			content_type='text/html',
		)

		server.expect_request('/page2').respond_with_data(
			'<html><head><title>Test Page 2</title></head><body><h1>Test Page 2</h1><p>This is test page 2</p></body></html>',
			content_type='text/html',
		)

		server.expect_request('/form').respond_with_data(
			"""
            <html>
            <head><title>Form Test Page</title></head>
            <body>
                <h1>Form Test</h1>
                <form id="testForm">
                    <input type="text" id="textInput" name="textInput" placeholder="Enter text">
                    <button type="submit" id="submitButton">Submit</button>
                </form>
                <div id="result"></div>
                <script>
                    document.getElementById('testForm').addEventListener('submit', function(e) {
                        e.preventDefault();
                        const input = document.getElementById('textInput').value;
                        document.getElementById('result').textContent = 'You entered: ' + input;
                    });
                </script>
            </body>
            </html>
            """,
			content_type='text/html',
		)

		yield server
		server.stop()

	@pytest.fixture
	def base_url(self, http_server):
		"""Return the base URL for the test HTTP server."""
		return f'http://{http_server.host}:{http_server.port}'

	@pytest.fixture(scope='module')
	async def browser(self, request):
		"""Create and provide a Browser instance with configurable headless mode."""
		headless = request.param if hasattr(request, 'param') else True  # Default to True if not specified
		browser_instance = Browser(config=BrowserConfig(headless=headless))
		yield browser_instance
		await browser_instance.close()

	@pytest.mark.asyncio
	@pytest.mark.parametrize('browser', [False], indirect=True)  # Set headless to False for this test
	async def test_window_dimensions_on_headful_browser(self, browser, base_url):
		"""
		Test that window dimensions are correctly applied when using browser.new_context() with headless set to False.

		This test verifies that custom window dimensions are precisely applied when properly configured.
		"""
		custom_width = 1000
		custom_height = 600
		custom_config = BrowserContextConfig(
			window_width=custom_width,
			window_height=custom_height,
			no_viewport=False,  # Ensure viewport matches window size
		)

		async with await browser.new_context(config=custom_config) as context:
			# Navigate to a page
			await context.navigate_to(f'{base_url}/')

			# Get the current page
			page = await context.get_agent_current_page()

			# Check viewport dimensions (inner window size)
			viewport_size = await page.evaluate("""
                () => {
                    return {
                        width: window.innerWidth,
                        height: window.innerHeight
                    };
                }
            """)

			# Verify the viewport dimensions match exactly what was configured
			assert viewport_size['width'] == custom_width, (
				f'Viewport width should be exactly {custom_width}px, but got {viewport_size["width"]}px.'
			)
			assert viewport_size['height'] == custom_height, (
				f'Viewport height should be exactly {custom_height}px, but got {viewport_size["height"]}px.'
			)

			# Check window dimensions (outer window size)
			window_size = await page.evaluate("""
                () => {
                    return {
                        width: window.outerWidth,
                        height: window.outerHeight
                    };
                }
            """)

			# For outer window dimensions, we need to account for browser chrome/decorations
			assert window_size['width'] >= custom_width, (
				f'Window width should be greater than or equal to {custom_width}px, but got {window_size["width"]}px.'
			)
			assert window_size['height'] >= custom_height, (
				f'Window height should be greater than or equal to {custom_height}px, but got {window_size["height"]}px.'
			)
			assert context.config.window_width == custom_width
			assert context.config.window_height == custom_height
			assert not context.config.no_viewport

		# First, capture the default window dimensions before applying custom configuration
		async with await browser.new_context() as default_context:
			# Navigate to a page
			await default_context.navigate_to(f'{base_url}/')

			# Get the current page
			default_page = await default_context.get_agent_current_page()

			# Capture default window and viewport dimensions
			default_window_size = await default_page.evaluate("""
                () => {
                    return {
                        width: window.outerWidth,
                        height: window.outerHeight
                    };
                }
            """)

			default_viewport_size = await default_page.evaluate("""
                () => {
                    return {
                        width: window.innerWidth,
                        height: window.innerHeight
                    };
                }
            """)

		custom_width = default_viewport_size['width'] - 100
		custom_height = default_viewport_size['height'] - 100

		print('values send ', custom_width, custom_height)

		# New configuration with no_viewport=True
		custom_config_no_viewport = BrowserContextConfig(
			window_width=custom_width,
			window_height=custom_height,
			no_viewport=True,  # Let the window size determine the viewport
		)

		async with await browser.new_context(config=custom_config_no_viewport) as context:
			# Navigate to a page
			await context.navigate_to(f'{base_url}/')

			# Get the current page
			page = await context.get_agent_current_page()

			window_size = await page.evaluate("""
                () => {
                    return {
                        width: window.outerWidth,
                        height: window.outerHeight
                    };
                }
            """)

			# viewport values should remain same as default
			assert window_size['width'] == default_window_size['width'], (
				f'Window width ({window_size["width"]}px) should be equal to default viewport size ({default_window_size["width"]}px).'
			)
			assert window_size['height'] == default_window_size['height'], (
				f'Window height ({window_size["height"]}px) should be equal to default viewport size ({default_window_size["height"]}px).'
			)

			assert window_size['width'] != custom_width, (
				f'Window width ({window_size["width"]}px) should not be equal to {custom_width}px.'
			)
			assert window_size['height'] != custom_height, (
				f'Window height ({window_size["height"]}px) should not be equal to {custom_height}px.'
			)

			# Check viewport dimensions
			viewport_size = await page.evaluate("""
                () => {
                    return {
                        width: window.innerWidth,
                        height: window.innerHeight
                    };
                }
            """)

			# viewport values should remain same as default
			assert viewport_size['width'] == default_viewport_size['width'], (
				f'Viewport width ({viewport_size["width"]}px) should be equal to default viewport size ({default_viewport_size["width"]}px).'
			)
			assert viewport_size['height'] == default_viewport_size['height'], (
				f'Viewport height ({viewport_size["height"]}px) should be equal to default viewport size ({default_viewport_size["height"]}px).'
			)

			assert viewport_size['width'] != custom_width, (
				f'Viewport width ({viewport_size["width"]}px) should not be equal to {custom_width}px.'
			)
			assert viewport_size['height'] != custom_height, (
				f'Viewport height ({viewport_size["height"]}px) should not be equal to {custom_height}px.'
			)

			assert context.config.window_height == default_viewport_size['height']
			assert context.config.window_width == default_viewport_size['width']
			assert context.config.no_viewport

	@pytest.mark.asyncio
	async def test_window_dimensions_on_headless_browser(self, browser, base_url):
		"""
		Test that window dimensions are correctly applied when using browser.new_context().

		This test verifies that custom window dimensions are precisely applied when properly configured.
		"""
		# Test custom window dimensions with no_viewport=False
		custom_width = 1000
		custom_height = 600
		custom_config = BrowserContextConfig(
			window_width=custom_width,
			window_height=custom_height,
			no_viewport=False,  # Ensure viewport matches window size
		)

		async with await browser.new_context(config=custom_config) as context:
			# Navigate to a page
			await context.navigate_to(f'{base_url}/')

			# Get the current page
			page = await context.get_agent_current_page()

			# Check viewport dimensions (inner window size)
			viewport_size = await page.evaluate("""
                () => {
                    return {
                        width: window.innerWidth,
                        height: window.innerHeight
                    };
                }
            """)

			# Verify the viewport dimensions match exactly what was configured
			assert viewport_size['width'] == custom_width, (
				f'Viewport width should be exactly {custom_width}px, but got {viewport_size["width"]}px. '
			)
			assert viewport_size['height'] == custom_height, (
				f'Viewport height should be exactly {custom_height}px, but got {viewport_size["height"]}px. '
			)

			# Check window dimensions (outer window size)
			window_size = await page.evaluate("""
                () => {
                    return {
                        width: window.outerWidth,
                        height: window.outerHeight
                    };
                }
            """)

			# For outer window dimensions, we need to account for browser chrome/decorations
			# But In headless mode, window.innerWidth and window.outerWidth are usually equal or nearly equal, because there's no visible browser UI (no title bar, borders, tab strip, etc.). same for height.
			assert window_size['width'] == custom_width, (
				f'Window width should be exactly {custom_width}px, but got {window_size["width"]}px. '
			)
			assert window_size['height'] == custom_height, (
				f'Window height should be exactly {custom_height}px, but got {window_size["height"]}px. '
			)
			assert context.config.window_width == custom_width
			assert context.config.window_height == custom_height
			assert not context.config.no_viewport

		# Test with explicit viewport size and no_viewport=True
		# This tests that when no_viewport=True, the viewport size is determined by the window (only when headless = False)
		custom_width = 600
		custom_height = 300
		custom_config_no_viewport = BrowserContextConfig(
			window_width=custom_width,
			window_height=custom_height,
			no_viewport=True,  # Let the window size determine the viewport
		)

		async with await browser.new_context(config=custom_config_no_viewport) as context:
			# Navigate to a page
			await context.navigate_to(f'{base_url}/')

			# Get the current page
			page = await context.get_agent_current_page()

			window_size = await page.evaluate("""
                () => {
                    return {
                        width: window.outerWidth,
                        height: window.outerHeight
                    };
                }
            """)

			# Verify window dimensions are set correctly
			assert window_size['width'] == custom_width, (
				f'Window width should be exactly {custom_width}px, but got {window_size["width"]}px.'
			)
			assert window_size['height'] == custom_height, (
				f'Window height should be exactly {custom_height}px, but got {window_size["height"]}px.'
			)

			# Check viewport dimensions
			viewport_size = await page.evaluate("""
                () => {
                    return {
                        width: window.innerWidth,
                        height: window.innerHeight
                    };
                }
            """)

			assert viewport_size['width'] == custom_width, (
				f'Viewport width should be exactly {custom_width}px, but got {viewport_size["width"]}px.'
			)
			assert viewport_size['height'] == custom_height, (
				f'Viewport height should be exactly {custom_height}px, but got {viewport_size["height"]}px.'
			)

			assert context.config.window_width == custom_width
			assert context.config.window_height == custom_height
			assert context.config.no_viewport
