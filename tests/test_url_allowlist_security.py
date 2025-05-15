import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig


class TestUrlAllowlistSecurity:
	"""Tests for URL allowlist security bypass prevention and URL allowlist glob pattern matching."""

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

	def test_glob_pattern_matching(self):
		"""Test that glob patterns in allowed_domains work correctly."""
		# Test *.example.com pattern (should match subdomains and main domain)
		glob_config = BrowserContextConfig(allowed_domains=['*.example.com'])
		glob_context = BrowserContext(browser=None, config=glob_config)

		# Should match subdomains
		assert glob_context._is_url_allowed('https://sub.example.com') is True
		assert glob_context._is_url_allowed('https://deep.sub.example.com') is True

		# Should also match main domain
		assert glob_context._is_url_allowed('https://example.com') is True

		# Should not match other domains
		assert glob_context._is_url_allowed('https://notexample.com') is False
		assert glob_context._is_url_allowed('https://example.org') is False

		# Test more complex glob patterns
		stars_config = BrowserContextConfig(allowed_domains=['*google.com', 'wiki*'])
		stars_context = BrowserContext(browser=None, config=stars_config)

		# Should match domains ending with google.com
		assert stars_context._is_url_allowed('https://google.com') is True
		assert stars_context._is_url_allowed('https://www.google.com') is True
		assert stars_context._is_url_allowed('https://anygoogle.com') is True

		# Should match domains starting with wiki
		assert stars_context._is_url_allowed('https://wiki.org') is True
		assert stars_context._is_url_allowed('https://wikipedia.org') is True

		# Should not match other domains
		assert stars_context._is_url_allowed('https://example.com') is False

		# Test browser internal URLs
		assert stars_context._is_url_allowed('chrome://settings') is True
		assert stars_context._is_url_allowed('about:blank') is True

		# Test security for glob patterns (authentication credentials bypass attempts)
		# These should all be detected as malicious despite containing allowed domain patterns
		assert glob_context._is_url_allowed('https://allowed.example.com:password@notallowed.com') is False
		assert glob_context._is_url_allowed('https://subdomain.example.com@evil.com') is False
		assert glob_context._is_url_allowed('https://sub.example.com%20@malicious.org') is False
		assert stars_context._is_url_allowed('https://anygoogle.com@evil.org') is False

	def test_glob_pattern_edge_cases(self):
		"""Test edge cases for glob pattern matching to ensure proper behavior."""
		# Test with domains containing glob pattern in the middle
		stars_config = BrowserContextConfig(allowed_domains=['*google.com', 'wiki*'])
		stars_context = BrowserContext(browser=None, config=stars_config)

		# Verify that 'wiki*' pattern doesn't match domains that merely contain 'wiki' in the middle
		assert stars_context._is_url_allowed('https://notawiki.com') is False
		assert stars_context._is_url_allowed('https://havewikipages.org') is False
		assert stars_context._is_url_allowed('https://my-wiki-site.com') is False

		# Verify that '*google.com' doesn't match domains that have 'google' in the middle
		assert stars_context._is_url_allowed('https://mygoogle.company.com') is False

		# Create context with potentially risky glob pattern that demonstrates security concerns
		risky_config = BrowserContextConfig(allowed_domains=['*.google.*'])
		risky_context = BrowserContext(browser=None, config=risky_config)

		# Should match legitimate Google domains
		assert risky_context._is_url_allowed('https://www.google.com') is True
		assert risky_context._is_url_allowed('https://mail.google.co.uk') is True

		# But could also match potentially malicious domains with a subdomain structure
		# This demonstrates why such wildcard patterns can be risky
		assert risky_context._is_url_allowed('https://www.google.evil.com') is True

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
