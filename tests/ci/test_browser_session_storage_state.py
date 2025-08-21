"""
Test script for BrowserSession storage state functionality and event-driven storage state.

Tests cover:
- Loading storage state on browser start
- Saving storage state (including cookies and local storage)
- Verifying storage state is applied to browser context
- NEW: Event-driven storage state operations
"""

import json
import logging
import tempfile
from pathlib import Path

import pytest

pytest.skip('TODO: fix - uses removed browser_context attribute', allow_module_level=True)

from pytest_httpserver import HTTPServer

from browser_use.browser.events import SaveStorageStateEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

# Set up test logging
logger = logging.getLogger('browser_session_cookie_tests')


class TestBrowserSessionStorageState:
	"""Tests for BrowserSession storage state loading and saving functionality."""

	@pytest.fixture
	async def temp_storage_state_file(self):
		"""Create a temporary storage state file with test cookies and local storage."""
		with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
			storage_state = {
				'cookies': [
					{
						'name': 'test_cookie',
						'value': 'test_value',
						'domain': '127.0.0.1',
						'path': '/',
						'expires': -1,
						'httpOnly': False,
						'secure': False,
						'sameSite': 'Lax',
					},
					{
						'name': 'session_cookie',
						'value': 'session_12345',
						'domain': '127.0.0.1',
						'path': '/',
						'expires': -1,
						'httpOnly': True,
						'secure': False,
						'sameSite': 'Lax',
					},
				],
				'origins': [],  # Could add localStorage/sessionStorage data here
			}
			json.dump(storage_state, f)
			temp_path = Path(f.name)

		yield temp_path

		# Cleanup
		temp_path.unlink(missing_ok=True)

	@pytest.fixture
	async def browser_profile_with_storage_state(self, temp_storage_state_file):
		"""Create a BrowserProfile with storage_state set."""
		profile = BrowserProfile(headless=True, user_data_dir=None, storage_state=temp_storage_state_file)
		yield profile

	@pytest.fixture
	async def browser_session_with_storage_state(self, browser_profile_with_storage_state):
		"""Create a BrowserSession with storage state configured."""
		session = BrowserSession(browser_profile=browser_profile_with_storage_state)
		yield session
		# Cleanup
		try:
			await session.stop()
		except Exception:
			pass

	@pytest.fixture
	def http_server(self, httpserver: HTTPServer):
		"""Set up HTTP server with test endpoints."""
		# Endpoint that shows cookies
		httpserver.expect_request('/cookies').respond_with_data(
			"""
			<html>
			<body>
				<h1>Cookie Test Page</h1>
				<script>
					document.write('<p>Cookies: ' + document.cookie + '</p>');
				</script>
			</body>
			</html>
			""",
			content_type='text/html',
		)
		return httpserver

	async def test_storage_state_loaded_on_start(self, browser_session_with_storage_state, http_server):
		"""Test that storage state is loaded when browser starts."""
		# Import event classes
		from browser_use.browser.events import StorageStateLoadedEvent

		# Start the browser session
		await browser_session_with_storage_state.start()

		# Wait for storage state to be loaded
		try:
			await browser_session_with_storage_state.event_bus.expect(StorageStateLoadedEvent, timeout=5.0)
		except TimeoutError:
			pass  # It's okay if the event doesn't fire, we'll check cookies directly

		# Verify cookies were loaded by accessing browser context directly
		context = browser_session_with_storage_state.browser_context
		assert context is not None, 'Browser context should be available'

		cookies = await context.cookies()
		assert len(cookies) >= 2, (
			f'Expected at least 2 cookies to be loaded from storage state, but got {len(cookies)}: {cookies}'
		)

		# Check specific cookies
		cookie_names = {cookie['name'] for cookie in cookies}
		assert 'test_cookie' in cookie_names
		assert 'session_cookie' in cookie_names

		# Verify cookie values
		test_cookie = next(c for c in cookies if c['name'] == 'test_cookie')
		assert test_cookie['value'] == 'test_value'
		assert test_cookie['domain'] == '127.0.0.1'

	async def test_storage_state_cookies_available_in_page(self, browser_session_with_storage_state, http_server):
		"""Test that cookies from storage state are available to web pages."""
		# Start the browser session
		await browser_session_with_storage_state.start()

		# Navigate to test page
		page = await browser_session_with_storage_state.get_current_page()
		test_url = http_server.url_for('/cookies')
		await page.goto(test_url)

		# Check that cookies are available to the page
		page_cookies = await page.evaluate('document.cookie')

		# The test_cookie should be visible in document.cookie (httpOnly=False)
		# but session_cookie won't be visible (httpOnly=True)
		assert 'test_cookie=test_value' in page_cookies

		# Verify all cookies are in the context
		all_cookies = await browser_session_with_storage_state.browser_context.cookies()
		cookie_names = {c['name'] for c in all_cookies}
		assert 'test_cookie' in cookie_names
		assert 'session_cookie' in cookie_names  # This one is httpOnly

	async def test_save_storage_state(self, browser_profile_with_storage_state, temp_storage_state_file):
		"""Test saving storage state to file."""
		# Create a new temp file for saving
		save_path = temp_storage_state_file.parent / 'saved_storage_state.json'

		session = BrowserSession(browser_profile=browser_profile_with_storage_state)
		await session.start()

		# Navigate to a page and set a new cookie
		page = await session.get_current_page()
		await page.goto('about:blank')
		await page.context.add_cookies([{'name': 'new_cookie', 'value': 'new_value', 'domain': '127.0.0.1', 'path': '/'}])

		# Save storage state (which includes cookies)
		await session.save_storage_state(save_path)

		# Verify saved file exists and contains cookies
		assert save_path.exists()
		saved_storage = json.loads(save_path.read_text())
		saved_cookies = saved_storage.get('cookies', [])
		assert len(saved_cookies) >= 3  # Original 2 + 1 new

		cookie_names = {cookie['name'] for cookie in saved_cookies}
		assert 'new_cookie' in cookie_names

		# Cleanup
		save_path.unlink(missing_ok=True)
		await session.kill()

	async def test_nonexistent_storage_state_file(self):
		"""Test that browser starts normally when storage_state file doesn't exist."""
		# Use a non-existent file path
		profile = BrowserProfile(headless=True, user_data_dir=None, storage_state=Path('/tmp/nonexistent_storage_state.json'))

		session = BrowserSession(browser_profile=profile)
		# Should start without errors
		await session.start()

		# Should have no cookies from localhost (our test domain)
		# Note: Browser may have cookies from default pages like Google's new tab page
		context = session.browser_context
		assert context is not None
		cookies = await context.cookies()
		localhost_cookies = [c for c in cookies if c.get('domain', '') in ['127.0.0.1', '.127.0.0.1']]
		assert len(localhost_cookies) == 0, f'Expected no 127.0.0.1 cookies, but found: {localhost_cookies}'

		await session.kill()

	async def test_invalid_storage_state_file(self, tmp_path):
		"""Test that browser handles invalid storage state file gracefully."""
		# Create a file with invalid JSON
		invalid_file = tmp_path / 'invalid_storage_state.json'
		invalid_file.write_text('not valid json')

		profile = BrowserProfile(headless=True, user_data_dir=None, storage_state=invalid_file)

		session = BrowserSession(browser_profile=profile)
		# Should start without errors (warning logged)
		await session.kill()

		# Should have no cookies from localhost (our test domain)
		# Note: Browser may have cookies from default pages like Google's new tab page
		context = session.browser_context
		assert context is not None
		cookies = await context.cookies()
		localhost_cookies = [c for c in cookies if c.get('domain', '') in ['127.0.0.1', '.127.0.0.1']]
		assert len(localhost_cookies) == 0, f'Expected no 127.0.0.1 cookies, but found: {localhost_cookies}'

		await session.kill()


class TestStorageStateEventSystem:
	"""Tests for NEW event-driven storage state operations."""

	async def test_save_storage_state_event_dispatching(self, httpserver: HTTPServer, tmp_path: Path):
		"""Test that SaveStorageStateEvent can be dispatched directly."""
		# Create temporary storage file
		storage_file = tmp_path / 'event_test_storage.json'

		# Set up test page with cookies
		httpserver.expect_request('/cookie-test').respond_with_data(
			'<html><body><h1>Storage Event Test</h1></body></html>',
			content_type='text/html',
			headers={'Set-Cookie': 'test_event_cookie=event_value; Path=/'},
		)

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(headless=True, user_data_dir=None, storage_state=storage_file, keep_alive=False)
		)

		try:
			await browser_session.start()

			# Navigate to set cookies
			await browser_session.navigate(httpserver.url_for('/cookie-test'))

			# Dispatch SaveStorageStateEvent directly
			save_event = browser_session.event_bus.dispatch(SaveStorageStateEvent())
			await save_event

			# Verify storage file was created
			assert storage_file.exists(), 'Storage state file should be created by event handler'

			# Verify file contains cookies
			storage_data = json.loads(storage_file.read_text())
			assert 'cookies' in storage_data

		finally:
			await browser_session.kill()
