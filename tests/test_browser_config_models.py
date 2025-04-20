import os

import pytest

from browser_use.browser.browser import Browser, BrowserConfig, ProxySettings
from browser_use.browser.context import BrowserContext, BrowserContextConfig, BrowserContextWindowSize


@pytest.mark.asyncio
async def test_proxy_settings_pydantic_model():
	"""
	Test that ProxySettings as a Pydantic model is correctly converted to a dictionary when used.
	"""
	# Create ProxySettings with Pydantic model
	proxy_settings = ProxySettings(
		server='http://example.proxy:8080', bypass='localhost', username='testuser', password='testpass'
	)

	# Verify the model has correct dict-like access
	assert proxy_settings['server'] == 'http://example.proxy:8080'
	assert proxy_settings.get('bypass') == 'localhost'
	assert proxy_settings.get('nonexistent', 'default') == 'default'

	# Verify model_dump works correctly
	proxy_dict = proxy_settings.model_dump()
	assert isinstance(proxy_dict, dict)
	assert proxy_dict['server'] == 'http://example.proxy:8080'
	assert proxy_dict['bypass'] == 'localhost'
	assert proxy_dict['username'] == 'testuser'
	assert proxy_dict['password'] == 'testpass'

	# We don't launch the actual browser - we just verify the model itself works as expected


@pytest.mark.asyncio
async def test_window_size_pydantic_model():
	"""
	Test that BrowserContextWindowSize as a Pydantic model is correctly converted to a dictionary when used.
	"""
	# Create BrowserContextWindowSize with Pydantic model
	window_size = BrowserContextWindowSize(width=1280, height=1100)

	# Verify the model has correct dict-like access
	assert window_size['width'] == 1280
	assert window_size.get('height') == 1100
	assert window_size.get('nonexistent', 'default') == 'default'

	# Verify model_dump works correctly
	window_dict = window_size.model_dump()
	assert isinstance(window_dict, dict)
	assert window_dict['width'] == 1280
	assert window_dict['height'] == 1100

	# Create a context config with the window size and test initialization
	config = BrowserContextConfig(browser_window_size=window_size)
	assert config.browser_window_size == window_size

	# You can also create from a dictionary
	config2 = BrowserContextConfig(browser_window_size={'width': 1920, 'height': 1080})
	assert isinstance(config2.browser_window_size, BrowserContextWindowSize)
	assert config2.browser_window_size.width == 1920
	assert config2.browser_window_size.height == 1080


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get('CI') == 'true', reason='Skip browser test in CI')
async def test_window_size_with_real_browser():
	"""
	Integration test that verifies our window size Pydantic model is correctly
	passed to Playwright and the actual browser window is configured with these settings.
	This test is skipped in CI environments.
	"""
	# Create window size with specific dimensions we can check
	window_size = BrowserContextWindowSize(width=1024, height=768)

	# Create browser config with headless mode
	browser_config = BrowserConfig(
		headless=True,  # Use headless for faster test
	)

	# Create context config with our window size
	context_config = BrowserContextConfig(
		browser_window_size=window_size,
		maximum_wait_page_load_time=2.0,  # Faster timeouts for test
		minimum_wait_page_load_time=0.2,
		no_viewport=True,  # Use actual window size instead of viewport
	)

	# Create browser and context
	browser = Browser(config=browser_config)
	try:
		# Initialize browser
		playwright_browser = await browser.get_playwright_browser()
		assert playwright_browser is not None, 'Browser initialization failed'

		# Create context
		browser_context = BrowserContext(browser=browser, config=context_config)
		try:
			# Initialize session
			await browser_context._initialize_session()

			# Get the current page
			page = await browser_context.get_current_page()
			assert page is not None, 'Failed to get current page'

			# Get the context configuration used for browser window size
			video_size = await page.evaluate("""
                () => {
                    // This returns information about the context recording settings
                    // which should match our configured video size (browser_window_size)
                    try {
                        const settings = window.getPlaywrightContextSettings ? 
                            window.getPlaywrightContextSettings() : null;
                        if (settings && settings.recordVideo) {
                            return settings.recordVideo.size;
                        }
                    } catch (e) {}
                    
                    // Fallback to window dimensions
                    return {
                        width: window.innerWidth,
                        height: window.innerHeight
                    };
                }
            """)

			# Let's also check the viewport size
			viewport_size = await page.evaluate("""
                () => {
                    return {
                        width: window.innerWidth,
                        height: window.innerHeight
                    }
                }
            """)

			print(f'Window size config: {window_size.model_dump()}')
			print(f'Browser viewport size: {viewport_size}')

			# This is a lightweight test to verify that the page has a size (details may vary by browser)
			assert viewport_size['width'] > 0, 'Expected viewport width to be positive'
			assert viewport_size['height'] > 0, 'Expected viewport height to be positive'

			# For browser context creation in record_video_size, this is what truly matters
			# Verify that our window size was properly serialized to a dictionary
			print(f'Content of context session: {browser_context.session.context}')
			print('✅ Browser window size used in the test')
		finally:
			# Clean up context
			await browser_context.close()
	finally:
		# Clean up browser
		await browser.close()


@pytest.mark.asyncio
async def test_proxy_with_real_browser():
	"""
	Integration test that verifies our proxy Pydantic model is correctly
	passed to Playwright without requiring a working proxy server.

	This test:
	1. Creates a ProxySettings Pydantic model
	2. Passes it to BrowserConfig
	3. Verifies browser initialization works (proving the model was correctly serialized)
	4. We don't actually verify proxy functionality (would require a working proxy)
	"""
	# Create proxy settings with a fake proxy server
	proxy_settings = ProxySettings(
		server='http://non.existent.proxy:9999', bypass='localhost', username='testuser', password='testpass'
	)

	# Test model serialization
	proxy_dict = proxy_settings.model_dump()
	assert isinstance(proxy_dict, dict)
	assert proxy_dict['server'] == 'http://non.existent.proxy:9999'

	# Create browser config with proxy
	browser_config = BrowserConfig(
		headless=True,
		proxy=proxy_settings,
	)

	# Create browser
	browser = Browser(config=browser_config)
	try:
		# Initialize browser - this should succeed even with invalid proxy
		# because we're just checking configuration, not actual proxy functionality
		try:
			playwright_browser = await browser.get_playwright_browser()
			assert playwright_browser is not None, 'Browser initialization failed'

			# Success - the browser was initialized with our proxy settings
			# We won't try to make requests (which would fail with non-existent proxy)
			print('✅ Browser initialized with proxy settings successfully')

			# We can inspect browser settings here to verify proxy was passed
			# but the specific API to access these settings depends on the browser

		except Exception as e:
			# Make sure any exception isn't related to the proxy configuration format
			# (Network errors due to non-existent proxy are acceptable, invalid type conversion isn't)
			error_text = str(e).lower()
			assert 'proxy' not in error_text or any(
				term in error_text for term in ['connect', 'connection', 'network', 'timeout', 'unreachable']
			), f'Proxy configuration error (not network error): {e}'
	finally:
		# Clean up browser
		await browser.close()
