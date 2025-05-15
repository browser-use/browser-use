import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig


class TestUrlAllowlistSecurity:
	"""Tests for URL allowlist security bypass prevention."""

	def test_authentication_bypass_prevention(self):
		"""Test that the URL allowlist cannot be bypassed using authentication credentials."""
		# Create a context config with a sample allowed domain
		config = BrowserContextConfig(allowed_domains=['example.com'])
		context = BrowserContext(browser=None, config=config)

		# Security vulnerability test cases
		# These should all be detected as malicious despite containing "example.com"
		assert context._is_url_allowed('https://example.com:password@malicious.com') is False
		assert context._is_url_allowed('https://example.com@malicious.com') is False
		assert context._is_url_allowed('https://example.com%20@malicious.com') is False
		assert context._is_url_allowed('https://example.com%3A@malicious.com') is False

		# Make sure legitimate auth credentials still work
		assert context._is_url_allowed('https://user:password@example.com') is True

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
		yield server
		server.stop()

	@pytest.fixture(scope='module')
	async def browser(self):
		"""Create and provide a Browser instance."""
		browser_instance = Browser(
			config=BrowserConfig(
				headless=True,
			)
		)
		yield browser_instance
		await browser_instance.close()

	@pytest.mark.asyncio
	async def test_url_bypass_prevention_with_allowed_domains(self, http_server, browser):
		"""Test that allowed_domains config does not allow bypassing the URL allowlist."""

		# Serve the redirecting page
		redirect_page_html = """
		<html>
		<head><title>Redirecting...</title></head>
		<body>
			<h1>Redirecting...</h1>
			<script>
				setTimeout(function() {
					window.location.href = 'https://www.google.com'; // Redirect to a disallowed URL (google.com) after 2 seconds
				}, 2000);
			</script>
		</body>
		</html>
		"""

		# Serve the redirect page
		http_server.expect_request('/redirect').respond_with_data(redirect_page_html, content_type='text/html')

		# Create a context config with a sample allowed domain
		config = BrowserContextConfig(allowed_domains=['localhost'])

		# Create a new browser context
		context = BrowserContext(browser=browser, config=config)

		# Simulate loading the test page
		await context.navigate_to(f'http://{http_server.host}:{http_server.port}/redirect')

		# Initialize the DOM state to populate the selector map
		await context.get_state(cache_clickable_elements_hashes=True)

		# Wait for the redirect to occur
		await asyncio.sleep(4)  # Wait for the redirect to happen

		# Check that the navigation to the disallowed URL (google.com) was blocked
		current_page = await context.get_current_page()
		assert current_page.url == f'http://{http_server.host}:{http_server.port}/redirect', (
			'Expected to remain on the redirect page, navigation to the disallowed URL (google.com) should be blocked.'
		)

		# Optionally, check that the user does not navigate away from the original test page
		assert current_page.url != 'https://www.google.com', 'User should not navigate to the disallowed URL (google.com).'
