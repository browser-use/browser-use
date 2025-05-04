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
