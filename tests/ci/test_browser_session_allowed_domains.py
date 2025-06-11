from browser_use.browser import BrowserProfile, BrowserSession


class TestUrlAllowlistSecurity:
	"""Tests for URL allowlist security bypass prevention and URL allowlist glob pattern matching."""

	def test_authentication_bypass_prevention(self):
		"""Test that the URL allowlist cannot be bypassed using authentication credentials."""
		# Create a context config with a sample allowed domain
		browser_profile = BrowserProfile(allowed_domains=['example.com'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)

		# Security vulnerability test cases
		# These should all be detected as malicious despite containing "example.com"
		assert browser_session._is_url_allowed('https://example.com:password@malicious.com') is False
		assert browser_session._is_url_allowed('https://example.com@malicious.com') is False
		assert browser_session._is_url_allowed('https://example.com%20@malicious.com') is False
		assert browser_session._is_url_allowed('https://example.com%3A@malicious.com') is False

		# Make sure legitimate auth credentials still work
		assert browser_session._is_url_allowed('https://user:password@example.com') is True

	def test_glob_pattern_matching(self):
		"""Test that glob patterns in allowed_domains work correctly."""
		# Test *.example.com pattern (should match subdomains and main domain)
		browser_profile = BrowserProfile(allowed_domains=['*.example.com'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)

		# Should match subdomains
		assert browser_session._is_url_allowed('https://sub.example.com') is True
		assert browser_session._is_url_allowed('https://deep.sub.example.com') is True

		# Should also match main domain
		assert browser_session._is_url_allowed('https://example.com') is True

		# Should not match other domains
		assert browser_session._is_url_allowed('https://notexample.com') is False
		assert browser_session._is_url_allowed('https://example.org') is False

		# Test more complex glob patterns
		browser_profile = BrowserProfile(
			allowed_domains=['*.google.com', 'https://wiki.org', 'https://good.com', 'chrome://version', 'brave://*'],
			headless=True,
			user_data_dir=None,
		)
		browser_session = BrowserSession(browser_profile=browser_profile)

		# Should match domains ending with google.com
		assert browser_session._is_url_allowed('https://google.com') is True
		assert browser_session._is_url_allowed('https://www.google.com') is True
		assert (
			browser_session._is_url_allowed('https://evilgood.com') is False
		)  # make sure we dont allow *good.com patterns, only *.good.com

		# Should match domains starting with wiki
		assert browser_session._is_url_allowed('http://wiki.org') is False
		assert browser_session._is_url_allowed('https://wiki.org') is True

		# Should not match internal domains because scheme was not provided
		assert browser_session._is_url_allowed('chrome://google.com') is False
		assert browser_session._is_url_allowed('chrome://abc.google.com') is False

		# Test browser internal URLs
		assert browser_session._is_url_allowed('chrome://settings') is False
		assert browser_session._is_url_allowed('chrome://version') is True
		assert browser_session._is_url_allowed('chrome-extension://version/') is False
		assert browser_session._is_url_allowed('brave://anything/') is True
		assert browser_session._is_url_allowed('about:blank') is True

		# Test security for glob patterns (authentication credentials bypass attempts)
		# These should all be detected as malicious despite containing allowed domain patterns
		assert browser_session._is_url_allowed('https://allowed.example.com:password@notallowed.com') is False
		assert browser_session._is_url_allowed('https://subdomain.example.com@evil.com') is False
		assert browser_session._is_url_allowed('https://sub.example.com%20@malicious.org') is False
		assert browser_session._is_url_allowed('https://anygoogle.com@evil.org') is False

	def test_glob_pattern_edge_cases(self):
		"""Test edge cases for glob pattern matching to ensure proper behavior."""
		# Test with domains containing glob pattern in the middle
		browser_profile = BrowserProfile(allowed_domains=['*.google.com', 'https://wiki.org'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)

		# Verify that 'wiki*' pattern doesn't match domains that merely contain 'wiki' in the middle
		assert browser_session._is_url_allowed('https://notawiki.com') is False
		assert browser_session._is_url_allowed('https://havewikipages.org') is False
		assert browser_session._is_url_allowed('https://my-wiki-site.com') is False

		# Verify that '*google.com' doesn't match domains that have 'google' in the middle
		assert browser_session._is_url_allowed('https://mygoogle.company.com') is False

		# Create context with potentially risky glob pattern that demonstrates security concerns
		browser_profile = BrowserProfile(allowed_domains=['*.google.com', '*.google.co.uk'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)

		# Should match legitimate Google domains
		assert browser_session._is_url_allowed('https://www.google.com') is True
		assert browser_session._is_url_allowed('https://mail.google.co.uk') is True

		# Shouldn't match potentially malicious domains with a similar structure
		# This demonstrates why the previous pattern was risky and why it's now rejected
		assert browser_session._is_url_allowed('https://www.google.evil.com') is False
