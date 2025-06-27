"""
Test that screenshots work correctly in headless browser mode.
"""

import base64

from browser_use.browser import BrowserProfile, BrowserSession


class TestHeadlessScreenshots:
	"""Test screenshot functionality specifically in headless browsers"""

	async def test_screenshot_works_in_headless_mode(self, httpserver):
		"""Explicitly test that screenshots can be captured in headless=True mode"""
		# Create a browser session with headless=True
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,  # Explicitly set headless mode
				user_data_dir=None,
				keep_alive=False,
			)
		)

		try:
			# Start the session
			await browser_session.start()
			assert browser_session.initialized

			# Set up test page with visible content
			httpserver.expect_request('/').respond_with_data(
				"""<html>
				<head><title>Headless Screenshot Test</title></head>
				<body style="background: white; padding: 20px;">
					<h1 style="color: black;">This is a test page</h1>
					<p style="color: blue;">Testing screenshot capture in headless mode</p>
					<div style="width: 200px; height: 100px; background: red;">Red Box</div>
				</body>
				</html>""",
				content_type='text/html',
			)

			# Navigate to test page
			await browser_session.navigate(httpserver.url_for('/'))

			# Take screenshot
			screenshot_b64 = await browser_session.take_screenshot()

			# Verify screenshot was captured
			assert screenshot_b64 is not None
			assert isinstance(screenshot_b64, str)
			assert len(screenshot_b64) > 0

			# Decode and validate the screenshot
			screenshot_bytes = base64.b64decode(screenshot_b64)

			# Verify PNG signature
			assert screenshot_bytes.startswith(b'\x89PNG\r\n\x1a\n')
			# Should be a reasonable size (not just a blank image)
			assert len(screenshot_bytes) > 5000, f'Screenshot too small: {len(screenshot_bytes)} bytes'

			# Test full page screenshot
			full_page_screenshot = await browser_session.take_screenshot(full_page=True)
			assert full_page_screenshot is not None
			full_page_bytes = base64.b64decode(full_page_screenshot)
			assert full_page_bytes.startswith(b'\x89PNG\r\n\x1a\n')
			assert len(full_page_bytes) > 5000

		finally:
			await browser_session.stop()

	async def test_screenshot_with_state_summary_in_headless(self, httpserver):
		"""Test that get_state_summary includes screenshots in headless mode"""
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
			)
		)

		try:
			await browser_session.start()

			# Set up test page
			httpserver.expect_request('/').respond_with_data(
				'<html><body><h1>State Summary Test</h1></body></html>',
				content_type='text/html',
			)
			await browser_session.navigate(httpserver.url_for('/'))

			# Get state summary
			state = await browser_session.get_state_summary(cache_clickable_elements_hashes=False)

			# Verify screenshot is included
			assert state.screenshot is not None
			assert isinstance(state.screenshot, str)
			assert len(state.screenshot) > 0

			# Decode and validate
			screenshot_bytes = base64.b64decode(state.screenshot)
			assert screenshot_bytes.startswith(b'\x89PNG\r\n\x1a\n')
			assert len(screenshot_bytes) > 1000

		finally:
			await browser_session.stop()

	async def test_screenshot_graceful_handling_in_headless(self):
		"""Test that screenshot handling works correctly in headless mode even with closed pages"""
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
			)
		)

		try:
			await browser_session.start()

			# Close all pages to test edge case
			assert browser_session.browser_context is not None
			pages = browser_session.browser_context.pages
			for page in pages:
				await page.close()

			# Browser should auto-create a new page, so screenshot should still work
			screenshot = await browser_session.take_screenshot()
			# Should get a screenshot of the new blank page
			assert screenshot is not None
			assert isinstance(screenshot, str)
			assert len(screenshot) > 0

			# Get state summary should also work
			state = await browser_session.get_state_summary(cache_clickable_elements_hashes=False)
			# Should have a screenshot
			assert state.screenshot is not None
			assert isinstance(state.screenshot, str)

		finally:
			await browser_session.stop()

	async def test_parallel_screenshots_long_page(self, httpserver):
		"""Test screenshots in a highly parallel environment with a very long page"""
		import asyncio

		# Generate a very long page (50,000px+)
		long_content = []
		long_content.append('<html><head><title>Very Long Page</title></head>')
		long_content.append('<body style="margin: 0; padding: 0;">')

		# Add many div elements to create a 50,000px+ long page
		# Each div is 500px tall, so we need 100+ divs
		for i in range(120):
			color = f'rgb({i % 256}, {(i * 2) % 256}, {(i * 3) % 256})'
			long_content.append(
				f'<div style="height: 500px; background: {color}; '
				f'display: flex; align-items: center; justify-content: center; '
				f'font-size: 48px; color: white; text-shadow: 2px 2px 4px rgba(0,0,0,0.5);">'
				f'Section {i + 1} - Testing Parallel Screenshots'
				f'</div>'
			)

		long_content.append('</body></html>')
		html_content = ''.join(long_content)

		# Set up the test page
		httpserver.expect_request('/longpage').respond_with_data(
			html_content,
			content_type='text/html',
		)
		test_url = httpserver.url_for('/longpage')

		# Create 10 browser sessions
		browser_sessions = []
		for i in range(10):
			session = BrowserSession(
				browser_profile=BrowserProfile(
					headless=True,
					user_data_dir=None,
					keep_alive=False,
				)
			)
			browser_sessions.append(session)

		try:
			# Start all sessions in parallel
			print('Starting 10 browser sessions in parallel...')
			await asyncio.gather(*[session.start() for session in browser_sessions])

			# Navigate all sessions to the long page in parallel
			print('Navigating all sessions to the long test page...')
			await asyncio.gather(*[session.navigate(test_url) for session in browser_sessions])

			# Take screenshots from all sessions at the same time
			print('Taking screenshots from all 10 sessions simultaneously...')
			screenshot_tasks = [session.take_screenshot(full_page=True) for session in browser_sessions]
			screenshots = await asyncio.gather(*screenshot_tasks)

			# Verify all screenshots are valid
			print('Verifying all screenshots...')
			for i, screenshot in enumerate(screenshots):
				# Should not be None
				assert screenshot is not None, f'Session {i} returned None screenshot'
				assert isinstance(screenshot, str), f'Session {i} screenshot is not a string'
				assert len(screenshot) > 0, f'Session {i} screenshot is empty'

				# Decode and validate
				try:
					screenshot_bytes = base64.b64decode(screenshot)
				except Exception as e:
					raise AssertionError(f'Session {i} screenshot is not valid base64: {e}')

				# Verify PNG signature
				assert screenshot_bytes.startswith(b'\x89PNG\r\n\x1a\n'), f'Session {i} screenshot is not a valid PNG'

				# Full page screenshot should be reasonably large
				# Due to our 6,000px height limit, expect at least 30KB
				assert len(screenshot_bytes) > 5000, f'Session {i} screenshot too small: {len(screenshot_bytes)} bytes'

			print(f'All {len(screenshots)} screenshots validated successfully!')

			# Also test taking regular (viewport) screenshots in parallel
			print('Taking viewport screenshots from all sessions simultaneously...')
			viewport_screenshots = await asyncio.gather(
				*[session.take_screenshot(full_page=False) for session in browser_sessions]
			)

			# Verify viewport screenshots
			for i, screenshot in enumerate(viewport_screenshots):
				assert screenshot is not None, f'Session {i} viewport screenshot is None'
				screenshot_bytes = base64.b64decode(screenshot)
				assert screenshot_bytes.startswith(b'\x89PNG\r\n\x1a\n')
				# Viewport screenshots should be smaller than full page
				assert len(screenshot_bytes) > 5000, f'Session {i} viewport screenshot too small'

		finally:
			# Kill all sessions in parallel
			print('Killing all browser sessions...')
			# Use return_exceptions=True to prevent one failed kill from affecting others
			# This prevents "Future exception was never retrieved" errors
			results = await asyncio.gather(*[session.kill() for session in browser_sessions], return_exceptions=True)

			# Check that no exceptions were raised during cleanup
			for i, result in enumerate(results):
				if isinstance(result, Exception):
					print(f'Warning: Session {i} kill raised exception: {type(result).__name__}: {result}')
