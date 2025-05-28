"""
Test script for BrowserSession cookie functionality.

Tests cover:
- Loading cookies from cookies_file on browser start
- Saving cookies to cookies_file
- Verifying cookies are applied to browser context
"""

import json
import logging
import tempfile
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

# Set up test logging
logger = logging.getLogger('browser_session_cookie_tests')


class TestBrowserSessionCookies:
	"""Tests for BrowserSession cookie loading and saving functionality."""

	@pytest.fixture
	async def temp_cookies_file(self):
		"""Create a temporary cookies file with test cookies."""
		with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
			test_cookies = [
				{
					'name': 'test_cookie',
					'value': 'test_value',
					'domain': 'localhost',
					'path': '/',
					'expires': -1,
					'httpOnly': False,
					'secure': False,
					'sameSite': 'Lax',
				},
				{
					'name': 'session_cookie',
					'value': 'session_12345',
					'domain': 'localhost',
					'path': '/',
					'expires': -1,
					'httpOnly': True,
					'secure': False,
					'sameSite': 'Lax',
				},
			]
			json.dump(test_cookies, f)
			temp_path = Path(f.name)

		yield temp_path

		# Cleanup
		temp_path.unlink(missing_ok=True)

	@pytest.fixture
	async def browser_profile_with_cookies(self, temp_cookies_file):
		"""Create a BrowserProfile with cookies_file set."""
		profile = BrowserProfile(headless=True, user_data_dir=None, cookies_file=str(temp_cookies_file))
		yield profile

	@pytest.fixture
	async def browser_session_with_cookies(self, browser_profile_with_cookies):
		"""Create a BrowserSession with cookie file configured."""
		session = BrowserSession(browser_profile=browser_profile_with_cookies)
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

	async def test_cookies_loaded_on_start(self, browser_session_with_cookies, http_server):
		"""Test that cookies are loaded from cookies_file when browser starts."""
		# Start the browser session
		await browser_session_with_cookies.start()

		# Verify cookies were loaded
		cookies = await browser_session_with_cookies.get_cookies()
		assert len(cookies) >= 2, 'Expected at least 2 cookies to be loaded'

		# Check specific cookies
		cookie_names = {cookie['name'] for cookie in cookies}
		assert 'test_cookie' in cookie_names
		assert 'session_cookie' in cookie_names

		# Verify cookie values
		test_cookie = next(c for c in cookies if c['name'] == 'test_cookie')
		assert test_cookie['value'] == 'test_value'
		assert test_cookie['domain'] == 'localhost'

	async def test_cookies_available_in_page(self, browser_session_with_cookies, http_server):
		"""Test that loaded cookies are available to web pages."""
		# Start the browser session
		await browser_session_with_cookies.start()

		# Navigate to test page
		page = await browser_session_with_cookies.get_current_page()
		await page.goto(http_server.url_for('/cookies'))

		# Check that cookies are available to the page
		page_cookies = await page.evaluate('document.cookie')
		assert 'test_cookie=test_value' in page_cookies

	async def test_save_cookies(self, browser_profile_with_cookies, temp_cookies_file):
		"""Test saving cookies to file."""
		# Create a new temp file for saving
		save_path = temp_cookies_file.parent / 'saved_cookies.json'

		session = BrowserSession(browser_profile=browser_profile_with_cookies)
		await session.start()

		# Navigate to a page and set a new cookie
		page = await session.get_current_page()
		await page.goto('about:blank')
		await page.context.add_cookies([{'name': 'new_cookie', 'value': 'new_value', 'domain': 'localhost', 'path': '/'}])

		# Save cookies
		await session.save_cookies(save_path)

		# Verify saved file exists and contains cookies
		assert save_path.exists()
		saved_cookies = json.loads(save_path.read_text())
		assert len(saved_cookies) >= 3  # Original 2 + 1 new

		cookie_names = {cookie['name'] for cookie in saved_cookies}
		assert 'new_cookie' in cookie_names

		# Cleanup
		save_path.unlink(missing_ok=True)
		await session.stop()

	async def test_nonexistent_cookies_file(self):
		"""Test that browser starts normally when cookies_file doesn't exist."""
		# Use a non-existent file path
		profile = BrowserProfile(headless=True, user_data_dir=None, cookies_file='/tmp/nonexistent_cookies.json')

		session = BrowserSession(browser_profile=profile)
		# Should start without errors
		await session.start()

		# Should have no cookies
		cookies = await session.get_cookies()
		assert len(cookies) == 0

		await session.stop()

	async def test_invalid_cookies_file(self, tmp_path):
		"""Test that browser handles invalid cookie file gracefully."""
		# Create a file with invalid JSON
		invalid_file = tmp_path / 'invalid_cookies.json'
		invalid_file.write_text('not valid json')

		profile = BrowserProfile(headless=True, user_data_dir=None, cookies_file=str(invalid_file))

		session = BrowserSession(browser_profile=profile)
		# Should start without errors (warning logged)
		await session.start()

		# Should have no cookies
		cookies = await session.get_cookies()
		assert len(cookies) == 0

		await session.stop()

	async def test_relative_cookies_file_path(self, browser_profile_with_cookies):
		"""Test that relative cookies_file paths work correctly."""
		# Create profile with relative path
		profile = BrowserProfile(
			headless=True,
			user_data_dir=None,
			cookies_file='test_cookies.json',  # Relative path
			downloads_dir=browser_profile_with_cookies.downloads_dir,
		)

		# Copy test cookies to expected location
		expected_path = Path(profile.downloads_dir) / 'test_cookies.json'
		expected_path.parent.mkdir(parents=True, exist_ok=True)
		expected_path.write_text(
			json.dumps([{'name': 'relative_cookie', 'value': 'relative_value', 'domain': 'localhost', 'path': '/'}])
		)

		session = BrowserSession(browser_profile=profile)
		await session.start()

		cookies = await session.get_cookies()
		cookie_names = {cookie['name'] for cookie in cookies}
		assert 'relative_cookie' in cookie_names

		# Cleanup
		expected_path.unlink(missing_ok=True)
		await session.stop()
