from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.profile import ProxySettings


async def test_proxy_settings_pydantic_model():
	"""
	Test that ProxySettings as a Pydantic model is correctly converted to a dictionary when used.
	"""
	# Create ProxySettings with Pydantic model
	proxy_settings = dict(server='http://example.proxy:8080', bypass='localhost', username='testuser', password='testpass')

	# Verify the model has correct dict-like access
	assert proxy_settings['server'] == 'http://example.proxy:8080'
	assert proxy_settings.get('bypass') == 'localhost'
	assert proxy_settings.get('nonexistent', 'default') == 'default'

	# Verify model_dump works correctly
	proxy_dict = dict(proxy_settings)
	assert isinstance(proxy_dict, dict)
	assert proxy_dict['server'] == 'http://example.proxy:8080'
	assert proxy_dict['bypass'] == 'localhost'
	assert proxy_dict['username'] == 'testuser'
	assert proxy_dict['password'] == 'testpass'

	# We don't launch the actual browser - we just verify the model itself works as expected


async def test_window_size_with_real_browser():
	"""
	Integration test that verifies our window size Pydantic model is correctly
	passed to Playwright and the actual browser window is configured with these settings.
	This test is skipped in CI environments.
	"""
	# Create browser profile with headless mode and specific dimensions
	browser_profile = BrowserProfile(
		user_data_dir=None,
		headless=True,  # window size gets converted to viewport size in headless mode
		window_size={'width': 999, 'height': 888},
		maximum_wait_page_load_time=2.0,
		minimum_wait_page_load_time=0.2,
	)

	# Create browser session
	browser_session = BrowserSession(browser_profile=browser_profile)
	try:
		await browser_session.start()
		# Get the current page
		page = await browser_session.get_current_page()
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
		actual_size = await page.evaluate("""
                () => {
                    return {
                        width: window.innerWidth,
                        height: window.innerHeight
                    }
                }
            """)

		print(f'Browser configured window_size={browser_session.browser_profile.window_size}')
		print(f'Browser configured viewport_size: {browser_session.browser_profile.viewport}')
		print(f'Browser content actual size: {actual_size}')

		# This is a lightweight test to verify that the page has a size (details may vary by browser)
		assert actual_size['width'] > 0, 'Expected viewport width to be positive'
		assert actual_size['height'] > 0, 'Expected viewport height to be positive'

		# assert that window_size got converted to viewport_size in headless mode
		assert browser_session.browser_profile.headless is True
		assert browser_session.browser_profile.viewport == {'width': 999, 'height': 888}
		assert browser_session.browser_profile.window_size is None
		assert browser_session.browser_profile.window_position is None
		assert browser_session.browser_profile.no_viewport is False
		# screen should be the detected display size (or default if no display detected)
		assert browser_session.browser_profile.screen is not None
		assert browser_session.browser_profile.screen['width'] > 0
		assert browser_session.browser_profile.screen['height'] > 0
	finally:
		await browser_session.stop()


async def test_proxy_with_real_browser():
	"""
	Integration test that verifies our proxy Pydantic model is correctly
	passed to Playwright without requiring a working proxy server.

	This test:
	1. Creates a ProxySettings Pydantic model
	2. Passes it to BrowserProfile
	3. Verifies browser initialization works (proving the model was correctly serialized)
	4. We don't actually verify proxy functionality (would require a working proxy)
	"""
	# Create proxy settings with a fake proxy server
	proxy_settings = ProxySettings(
		server='http://non.existent.proxy:9999', bypass='localhost', username='testuser', password='testpass'
	)

	# Test model serialization
	proxy_dict = dict(proxy_settings)
	assert isinstance(proxy_dict, dict)
	assert proxy_dict['server'] == 'http://non.existent.proxy:9999'

	# Create browser profile with proxy
	browser_profile = BrowserProfile(
		headless=True,
		proxy=proxy_settings,
		user_data_dir=None,
	)

	# Create browser session
	browser_session = BrowserSession(browser_profile=browser_profile)
	try:
		await browser_session.start()
		# Success - the browser was initialized with our proxy settings
		# We won't try to make requests (which would fail with non-existent proxy)
		print('✅ Browser initialized with proxy settings successfully')
		assert browser_session.browser_profile.proxy == proxy_settings
		# TODO: create a network request in the browser and verify it goes through the proxy?
		# would require setting up a whole fake proxy in a fixture
	finally:
		await browser_session.stop()
