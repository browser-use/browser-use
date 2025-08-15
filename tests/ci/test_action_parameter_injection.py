import asyncio
import base64
import socketserver

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession

# Fix for httpserver hanging on shutdown - prevent blocking on socket close
socketserver.ThreadingMixIn.block_on_close = False
socketserver.ThreadingMixIn.daemon_threads = True


class TestBrowserContext:
	"""Tests for browser context functionality using real browser instances."""

	@pytest.fixture(scope='session')
	def http_server(self):
		"""Create and provide a test HTTP server that serves static content."""
		server = HTTPServer()
		server.start()

		# Add routes for test pages
		server.expect_request('/').respond_with_data(
			'<html><head><title>Test Home Page</title></head><body><h1>Test Home Page</h1><p>Welcome to the test site</p></body></html>',
			content_type='text/html',
		)

		server.expect_request('/scroll_test').respond_with_data(
			"""
            <html>
            <head>
                <title>Scroll Test</title>
                <style>
                    body { height: 3000px; }
                    .marker { position: absolute; }
                    #top { top: 0; }
                    #middle { top: 1000px; }
                    #bottom { top: 2000px; }
                </style>
            </head>
            <body>
                <div id="top" class="marker">Top of the page</div>
                <div id="middle" class="marker">Middle of the page</div>
                <div id="bottom" class="marker">Bottom of the page</div>
            </body>
            </html>
            """,
			content_type='text/html',
		)

		yield server
		server.stop()

	@pytest.fixture(scope='session')
	def base_url(self, http_server):
		"""Return the base URL for the test HTTP server."""
		return f'http://{http_server.host}:{http_server.port}'

	@pytest.fixture(scope='module')
	async def browser_session(self):
		"""Create and provide a BrowserSession instance with security disabled."""
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=True,
			)
		)
		await browser_session.start()
		yield browser_session
		await browser_session.kill()
		# Ensure event bus is properly stopped
		await browser_session.event_bus.stop(clear=True, timeout=5)

	def test_is_url_allowed(self):
		"""
		Test the _is_url_allowed method to verify that it correctly checks URLs against
		the allowed domains configuration.
		"""
		# Scenario 1: allowed_domains is None, any URL should be allowed.
		from bubus import EventBus

		from browser_use.browser.security_watchdog import SecurityWatchdog

		config1 = BrowserProfile(allowed_domains=None, headless=True, user_data_dir=None)
		context1 = BrowserSession(browser_profile=config1)
		event_bus1 = EventBus()
		watchdog1 = SecurityWatchdog(browser_session=context1, event_bus=event_bus1)
		assert watchdog1._is_url_allowed('http://anydomain.com') is True
		assert watchdog1._is_url_allowed('https://anotherdomain.org/path') is True

		# Scenario 2: allowed_domains is provided.
		# Note: match_url_with_domain_pattern defaults to https:// scheme when none is specified
		allowed = ['https://example.com', 'http://example.com', 'http://*.mysite.org', 'https://*.mysite.org']
		config2 = BrowserProfile(allowed_domains=allowed, headless=True, user_data_dir=None)
		context2 = BrowserSession(browser_profile=config2)
		event_bus2 = EventBus()
		watchdog2 = SecurityWatchdog(browser_session=context2, event_bus=event_bus2)

		# URL exactly matching
		assert watchdog2._is_url_allowed('http://example.com') is True
		# URL with subdomain (should not be allowed)
		assert watchdog2._is_url_allowed('http://sub.example.com/path') is False
		# URL with subdomain for wildcard pattern (should be allowed)
		assert watchdog2._is_url_allowed('http://sub.mysite.org') is True
		# URL that matches second allowed domain
		assert watchdog2._is_url_allowed('https://mysite.org/page') is True
		# URL with port number, still allowed (port is stripped)
		assert watchdog2._is_url_allowed('http://example.com:8080') is True
		assert watchdog2._is_url_allowed('https://example.com:443') is True

		# Scenario 3: Malformed URL or empty domain
		# urlparse will return an empty netloc for some malformed URLs.
		assert watchdog2._is_url_allowed('notaurl') is False

	def test_convert_simple_xpath_to_css_selector(self):
		"""
		Test removed: _convert_simple_xpath_to_css_selector method no longer exists.
		"""
		pass  # Method was removed from BrowserSession

	def test_enhanced_css_selector_for_element(self):
		"""
		Test removed: _enhanced_css_selector_for_element method no longer exists.
		"""
		pass  # Method was removed from BrowserSession

	@pytest.mark.asyncio
	async def test_navigate_and_get_current_page(self, browser_session, base_url):
		"""Test that navigate method changes the URL and get_current_page returns the proper page."""
		# Navigate to the test page
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/'))
		await event

		# Get the current page
		page = await browser_session.get_current_page()

		# Verify the page URL matches what we navigated to
		assert f'{base_url}/' in page.url

		# Verify the page title
		title = await page.title()
		assert title == 'Test Home Page'

	@pytest.mark.asyncio
	async def test_refresh_page(self, browser_session, base_url):
		"""Test that refresh_page correctly reloads the current page."""
		# Navigate to the test page
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/'))
		await event

		# Get the current page before refresh
		page_before = await browser_session.get_current_page()

		# Refresh the page
		await browser_session.refresh()

		# Get the current page after refresh
		page_after = await browser_session.get_current_page()

		# Verify it's still on the same URL
		assert page_after.url == page_before.url

		# Verify the page title is still correct
		title = await page_after.title()
		assert title == 'Test Home Page'

	@pytest.mark.asyncio
	async def test_execute_javascript(self, browser_session, base_url):
		"""Test that execute_javascript correctly executes JavaScript in the current page."""
		# Navigate to a test page
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/'))
		await event

		# Execute a simple JavaScript snippet that returns a value
		result = await browser_session.execute_javascript('document.title')

		# Verify the result
		assert result == 'Test Home Page'

		# Execute JavaScript that modifies the page
		await browser_session.execute_javascript("document.body.style.backgroundColor = 'red'")

		# Verify the change by reading back the value
		bg_color = await browser_session.execute_javascript('document.body.style.backgroundColor')
		assert bg_color == 'red'

	@pytest.mark.asyncio
	async def test_get_scroll_info(self, browser_session, base_url):
		"""Test that get_scroll_info returns the correct scroll position information."""
		# Navigate to the scroll test page
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/scroll_test'))
		await event
		page = await browser_session.get_current_page()

		# Get initial scroll info
		pixels_above_initial, pixels_below_initial = await browser_session.get_scroll_info(page)

		# Verify initial scroll position
		assert pixels_above_initial == 0, 'Initial scroll position should be at the top'
		assert pixels_below_initial > 0, 'There should be content below the viewport'

		# Scroll down the page
		await browser_session.execute_javascript('window.scrollBy(0, 500)')
		await asyncio.sleep(0.2)  # Brief delay for scroll to complete

		# Get new scroll info
		pixels_above_after_scroll, pixels_below_after_scroll = await browser_session.get_scroll_info(page)

		# Verify new scroll position
		assert pixels_above_after_scroll > 0, 'Page should be scrolled down'
		assert pixels_above_after_scroll >= 400, 'Page should be scrolled down at least 400px'
		assert pixels_below_after_scroll < pixels_below_initial, 'Less content should be below viewport after scrolling'

	@pytest.mark.asyncio
	async def test_take_screenshot(self, browser_session, base_url):
		"""Test that take_screenshot returns a valid base64 encoded image."""
		# Navigate to the test page
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/'))
		await event

		# Take a screenshot
		screenshot_base64 = await browser_session.take_screenshot()

		# Verify the screenshot is a valid base64 string
		assert isinstance(screenshot_base64, str)
		assert len(screenshot_base64) > 0

		# Verify it can be decoded as base64
		try:
			image_data = base64.b64decode(screenshot_base64)
			# Verify the data starts with a valid image signature (PNG file header)
			assert image_data[:8] == b'\x89PNG\r\n\x1a\n', 'Screenshot is not a valid PNG image'
		except Exception as e:
			pytest.fail(f'Failed to decode screenshot as base64: {e}')

	@pytest.mark.asyncio
	async def test_switch_tab_operations(self, browser_session, base_url):
		"""Test tab creation, switching, and closing operations."""
		# Navigate to home page in first tab
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/'))
		await event

		# Create a new tab
		await browser_session.create_new_tab(f'{base_url}/scroll_test')

		# Verify we have two tabs now
		tabs_info = await browser_session.get_tabs_info()
		assert len(tabs_info) == 2, 'Should have two tabs open'

		# Verify current tab is the scroll test page
		current_page = await browser_session.get_current_page()
		assert f'{base_url}/scroll_test' in current_page.url

		# Switch back to the first tab
		await browser_session.switch_to_tab(0)

		# Verify we're back on the home page
		current_page = await browser_session.get_current_page()
		assert f'{base_url}/' in current_page.url

		# Close the second tab
		await browser_session.close_tab(1)

		# Verify we have the expected number of tabs
		# The first tab remains plus any about:blank tabs created by AboutBlankWatchdog
		tabs_info = await browser_session.get_tabs_info()
		# Filter out about:blank tabs created by the watchdog
		non_blank_tabs = [tab for tab in tabs_info if 'about:blank' not in tab.url]
		assert len(non_blank_tabs) == 1, (
			f'Should have one non-blank tab open after closing the second, but got {len(non_blank_tabs)}: {non_blank_tabs}'
		)
		assert base_url in non_blank_tabs[0].url, 'The remaining tab should be the home page'

	# TODO: highlighting doesn't exist anymore
	# @pytest.mark.asyncio
	# async def test_remove_highlights(self, browser_session, base_url):
	# 	"""Test that remove_highlights successfully removes highlight elements."""
	# 	# Navigate to a test page
	# 	from browser_use.browser.events import NavigateToUrlEvent; event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/')

	# 	# Add a highlight via JavaScript
	# 	await browser_session.execute_javascript("""
	#         const container = document.createElement('div');
	#         container.id = 'playwright-highlight-container';
	#         document.body.appendChild(container);

	#         const highlight = document.createElement('div');
	#         highlight.id = 'playwright-highlight-1';
	#         container.appendChild(highlight);

	#         const element = document.querySelector('h1');
	#         element.setAttribute('browser-user-highlight-id', 'playwright-highlight-1');
	#     """)

	# 	# Verify the highlight container exists
	# 	container_exists = await browser_session.execute_javascript(
	# 		"document.getElementById('playwright-highlight-container') !== null"
	# 	)
	# 	assert container_exists, 'Highlight container should exist before removal'

	# 	# Call remove_highlights
	# 	await browser_session.remove_highlights()

	# 	# Verify the highlight container was removed
	# 	container_exists_after = await browser_session.execute_javascript(
	# 		"document.getElementById('playwright-highlight-container') !== null"
	# 	)
	# 	assert not container_exists_after, 'Highlight container should be removed'

	# 	# Verify the highlight attribute was removed from the element
	# 	attribute_exists = await browser_session.execute_javascript(
	# 		"document.querySelector('h1').hasAttribute('browser-user-highlight-id')"
	# 	)
	# 	assert not attribute_exists, 'browser-user-highlight-id attribute should be removed'

	@pytest.mark.asyncio
	async def test_custom_action_with_no_arguments(self, browser_session, base_url):
		"""Test that custom actions with no arguments are handled correctly"""
		from browser_use.agent.views import ActionResult
		from browser_use.controller.registry.service import Registry

		# Create a registry
		registry = Registry()

		# Register a custom action with no arguments
		@registry.action('Some custom action with no args')
		def simple_action():
			return ActionResult(extracted_content='return some result')

		# Navigate to a test page
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/'))
		await event

		# Execute the action
		result = await registry.execute_action('simple_action', {})

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content == 'return some result'

		# Test that the action model is created correctly
		action_model = registry.create_action_model()

		# The action should be in the model fields
		assert 'simple_action' in action_model.model_fields

		# Create an instance with the simple_action
		action_instance = action_model(simple_action={})  # type: ignore[call-arg]

		# Test that model_dump works correctly
		dumped = action_instance.model_dump(exclude_unset=True)
		assert 'simple_action' in dumped
		assert dumped['simple_action'] == {}

		# Test async version as well
		@registry.action('Async custom action with no args')
		async def async_simple_action():
			return ActionResult(extracted_content='async result')

		result = await registry.execute_action('async_simple_action', {})
		assert result.extracted_content == 'async result'

		# Test with special parameters but no regular arguments
		@registry.action('Action with only special params')
		async def special_params_only(browser_session):
			page = await browser_session.get_current_page()
			return ActionResult(extracted_content=f'Page URL: {page.url}')

		result = await registry.execute_action('special_params_only', {}, browser_session=browser_session)
		assert 'Page URL:' in result.extracted_content
		assert base_url in result.extracted_content
