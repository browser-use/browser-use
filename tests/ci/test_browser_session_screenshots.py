"""
Test that screenshots work correctly in headless browser mode.
"""

import asyncio
import base64
import time

import pytest

from browser_use.browser import BrowserProfile, BrowserSession


class TestHeadlessScreenshots:
	"""Test screenshot functionality specifically in headless browsers"""

	@pytest.mark.skip(reason='TODO: fix')
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
			assert browser_session._browser_context is not None

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
			await browser_session.kill()

	@pytest.mark.skip(reason='TODO: fix')
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
			state = await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=False)

			# Verify screenshot is included
			assert state.screenshot is not None
			assert isinstance(state.screenshot, str)
			assert len(state.screenshot) > 0

			# Decode and validate
			screenshot_bytes = base64.b64decode(state.screenshot)
			assert screenshot_bytes.startswith(b'\x89PNG\r\n\x1a\n')
			assert len(screenshot_bytes) > 1000

		finally:
			await browser_session.kill()

	@pytest.mark.skip(reason='TODO: fix')
	async def test_screenshot_graceful_handling_in_headless(self, httpserver):
		"""Test that screenshot handling works correctly in headless mode even with closed pages"""
		# Set up test page
		httpserver.expect_request('/test').respond_with_data(
			'<html><body><h1>Test Page</h1></body></html>', content_type='text/html'
		)

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

			# Browser should auto-create a new page on about:blank with animation
			# With AboutBlankWatchdog, about:blank pages now have animated content, so they should have screenshots
			state = await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=False)
			assert state.screenshot is not None, 'Screenshot should not be None for animated about:blank pages'
			assert state.url == 'about:blank' or state.url.startswith('chrome://'), f'Expected empty page but got {state.url}'

			# Now navigate to a real page and verify screenshot works
			await browser_session.navigate(httpserver.url_for('/test'))

			# Get state with screenshot
			state = await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=False)
			# Should have a screenshot now
			assert state.screenshot is not None, 'Screenshot should not be None for real pages'
			assert isinstance(state.screenshot, str)
			assert len(state.screenshot) > 100, 'Screenshot should have substantial content'
			assert 'test' in state.url.lower()

		finally:
			await browser_session.kill()

	@pytest.mark.skip(reason='TODO: fix')
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
			# Start all sessions sequentially to avoid playwright_global_object semaphore contention
			# The playwright global object semaphore only allows 1 concurrent initialization
			print('Starting 10 browser sessions sequentially...')
			for i, session in enumerate(browser_sessions):
				print(f'Starting session {i + 1}/10...')
				await session.start()

			# Navigate all sessions to the long page in parallel
			print('Navigating all sessions to the long test page...')
			await asyncio.gather(*[session.navigate(test_url) for session in browser_sessions])

			# Take screenshots from all sessions
			# Due to semaphore_limit=1, these will execute sequentially
			print('Taking screenshots from all 10 sessions...')
			start_time = time.time()
			screenshot_tasks = [session.take_screenshot() for session in browser_sessions]

			# Use return_exceptions=True to handle any failures gracefully
			results = await asyncio.gather(*screenshot_tasks, return_exceptions=True)
			total_time = time.time() - start_time

			# Verify timing - with semaphore_limit=1, screenshots execute sequentially
			# Each screenshot should take ~1.5s, so 10 × 1.5s = 15s, allow up to 30s for overhead
			assert total_time < 30, f'Screenshots took too long: {total_time:.1f}s (should be < 30s)'
			print(f'All screenshot attempts completed in {total_time:.1f}s')

			# Separate successful screenshots from failures
			screenshots = []
			failures = []
			for i, result in enumerate(results):
				if isinstance(result, Exception):
					failures.append((i, result))
					print(f'Session {i} failed: {type(result).__name__}: {result}')
				else:
					screenshots.append(result)
					print(f'Session {i} screenshot completed successfully')

			# ALL screenshots must succeed
			assert len(failures) == 0, (
				f'{len(failures)} screenshots failed: {[(i, type(e).__name__, str(e)) for i, e in failures]}'
			)
			assert len(screenshots) == 10, f'Expected 10 successful screenshots, got {len(screenshots)}'
			print('✅ All 10 screenshots captured successfully!')

			# Verify all screenshots are valid
			print('Verifying all 10 screenshots...')
			for i, screenshot in enumerate(screenshots):
				# Should not be None
				assert screenshot is not None, f'Screenshot {i} returned None'
				assert isinstance(screenshot, str), f'Screenshot {i} is not a string'
				assert len(screenshot) > 0, f'Screenshot {i} is empty'

				# Decode and validate
				try:
					screenshot_bytes = base64.b64decode(screenshot)
				except Exception as e:
					raise AssertionError(f'Screenshot {i} is not valid base64: {e}')

				# Verify PNG signature
				assert screenshot_bytes.startswith(b'\x89PNG\r\n\x1a\n'), f'Screenshot {i} is not a valid PNG'

				# Full page screenshot should be reasonably large
				# Due to our 6,000px height limit, expect at least 5KB
				assert len(screenshot_bytes) > 20, f'Screenshot {i} too small: {len(screenshot_bytes)} bytes'
				if len(screenshot_bytes) < 500:
					print(
						f'⚠️ Screenshot {i} failed to be taken in time, it returned a blank image instead: {len(screenshot_bytes)} bytes, perhaps the page failed to load in time?'
					)

			print('✅ All 10 screenshots validated successfully!')

			# Also test taking regular (viewport) screenshots
			print('\nTaking viewport screenshots from all sessions...')
			start_time = time.time()
			viewport_results = await asyncio.gather(
				*[session.take_screenshot() for session in browser_sessions], return_exceptions=True
			)
			viewport_time = time.time() - start_time
			assert viewport_time < 30, f'Viewport screenshots took too long: {viewport_time:.1f}s (should be < 30s)'
			print(f'All viewport screenshot attempts completed in {viewport_time:.1f}s')

			# Check for failures
			viewport_screenshots = []
			viewport_failures = []
			for i, result in enumerate(viewport_results):
				if isinstance(result, Exception):
					viewport_failures.append((i, result))
					print(f'Session {i} viewport failed: {type(result).__name__}: {result}')
				else:
					viewport_screenshots.append(result)
					print(f'Session {i} viewport screenshot completed successfully')

			# ALL viewport screenshots must succeed
			assert len(viewport_failures) == 0, (
				f'{len(viewport_failures)} viewport screenshots failed: {[(i, type(e).__name__, str(e)) for i, e in viewport_failures]}'
			)
			assert len(viewport_screenshots) == 10, (
				f'Expected 10 successful viewport screenshots, got {len(viewport_screenshots)}'
			)
			print('✅ All 10 viewport screenshots captured successfully!')

			# Verify all 10 viewport screenshots
			print('Verifying all 10 viewport screenshots...')
			for i, screenshot in enumerate(viewport_screenshots):
				assert screenshot is not None, f'Viewport screenshot {i} is None'
				screenshot_bytes = base64.b64decode(screenshot)
				assert screenshot_bytes.startswith(b'\x89PNG\r\n\x1a\n'), f'Viewport screenshot {i} is not a valid PNG'
				# Viewport screenshots should be reasonably sized
				assert len(screenshot_bytes) > 10, f'Viewport screenshot {i} too small: {len(screenshot_bytes)} bytes'
			print('✅ All 10 viewport screenshots validated successfully!')

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

	@pytest.mark.skip(reason='TODO: fix')
	async def test_screenshot_at_bottom_of_page(self, httpserver):
		"""Test screenshot capture when scrolled to bottom of page (regression test for clipping issue)"""
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=False,
			)
		)

		try:
			await browser_session.start()

			# Create a page with scrollable content
			httpserver.expect_request('/scrollable').respond_with_data(
				"""<html>
				<head><title>Scrollable Page Test</title></head>
				<body style="margin: 0; padding: 0;">
					<div style="height: 3000px; background: linear-gradient(to bottom, red, yellow, green, blue);">
						<div style="position: absolute; top: 0; left: 10px; font-size: 24px;">Top of page</div>
						<div style="position: absolute; top: 50%; left: 10px; font-size: 24px;">Middle of page</div>
						<div style="position: absolute; bottom: 10px; left: 10px; font-size: 24px;">Bottom of page</div>
					</div>
				</body>
				</html>""",
				content_type='text/html',
			)

			# Navigate to test page
			await browser_session.navigate(httpserver.url_for('/scrollable'))
			page = browser_session.page
			assert page is not None

			# Test 1: Screenshot at top of page (should work)
			screenshot_top = await browser_session.take_screenshot()
			assert screenshot_top is not None
			assert len(base64.b64decode(screenshot_top)) > 5000

			# Test 2: Screenshot at middle of page
			await page.evaluate('window.scrollTo(0, document.body.scrollHeight / 2)')
			await asyncio.sleep(0.1)  # Wait for scroll
			screenshot_middle = await browser_session.take_screenshot()
			assert screenshot_middle is not None
			assert len(base64.b64decode(screenshot_middle)) > 5000

			# Test 3: Screenshot at bottom of page (this was failing with clipping error)
			await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
			await asyncio.sleep(0.1)  # Wait for scroll

			# This should not raise "Clipped area is either empty or outside the resulting image" error
			screenshot_bottom = await browser_session.take_screenshot()
			assert screenshot_bottom is not None
			assert len(base64.b64decode(screenshot_bottom)) > 5000

			# Test 4: Screenshot when scrolled beyond page bottom (edge case)
			await page.evaluate('window.scrollTo(0, document.body.scrollHeight + 1000)')
			await asyncio.sleep(0.1)
			screenshot_beyond = await browser_session.take_screenshot()
			assert screenshot_beyond is not None
			assert len(base64.b64decode(screenshot_beyond)) > 5000

			print('✅ All screenshot positions tested successfully!')

		finally:
			await browser_session.kill()


class TestScreenshotEventSystem:
	"""Tests for NEW event-driven screenshot infrastructure only."""

	@pytest.mark.skip(reason='TODO: fix')
	async def test_screenshot_response_event_dispatching(self, httpserver):
		"""Test that ScreenshotResponseEvent is properly dispatched by event handlers."""
		from browser_use.browser.events import ScreenshotEvent

		browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=False))

		try:
			await browser_session.start()

			# Set up test page
			httpserver.expect_request('/event-test').respond_with_data(
				'<html><body><h1>Screenshot Event Test</h1></body></html>',
				content_type='text/html',
			)
			await browser_session.navigate(httpserver.url_for('/event-test'))

			# Test the NEW event-driven path: direct event dispatching
			event = browser_session.event_bus.dispatch(ScreenshotEvent(full_page=False))
			screenshot_result = (await event.event_result()) or {}
			assert screenshot_result.get('screenshot')
			assert isinstance(screenshot_result['screenshot'], str)
			assert len(base64.b64decode(screenshot_result['screenshot'])) > 5000

		finally:
			await browser_session.kill()
