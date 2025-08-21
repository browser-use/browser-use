from browser_use.browser import BrowserProfile, BrowserSession


class TestUrlAllowlistSecurity:
	"""Tests for URL allowlist security bypass prevention and URL allowlist glob pattern matching."""

	def test_authentication_bypass_prevention(self):
		"""Test that the URL allowlist cannot be bypassed using authentication credentials."""
		from bubus import EventBus

		from browser_use.browser.security_watchdog import SecurityWatchdog

		# Create a context config with a sample allowed domain
		browser_profile = BrowserProfile(allowed_domains=['example.com'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Security vulnerability test cases
		# These should all be detected as malicious despite containing "example.com"
		assert watchdog._is_url_allowed('https://example.com:password@malicious.com') is False
		assert watchdog._is_url_allowed('https://example.com@malicious.com') is False
		assert watchdog._is_url_allowed('https://example.com%20@malicious.com') is False
		assert watchdog._is_url_allowed('https://example.com%3A@malicious.com') is False

		# Make sure legitimate auth credentials still work
		assert watchdog._is_url_allowed('https://user:password@example.com') is True

	def test_glob_pattern_matching(self):
		"""Test that glob patterns in allowed_domains work correctly."""
		from bubus import EventBus

		from browser_use.browser.security_watchdog import SecurityWatchdog

		# Test *.example.com pattern (should match subdomains and main domain)
		browser_profile = BrowserProfile(allowed_domains=['*.example.com'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Should match subdomains
		assert watchdog._is_url_allowed('https://sub.example.com') is True
		assert watchdog._is_url_allowed('https://deep.sub.example.com') is True

		# Should also match main domain
		assert watchdog._is_url_allowed('https://example.com') is True

		# Should not match other domains
		assert watchdog._is_url_allowed('https://notexample.com') is False
		assert watchdog._is_url_allowed('https://example.org') is False

		# Test more complex glob patterns
		browser_profile = BrowserProfile(
			allowed_domains=['*.google.com', 'https://wiki.org', 'https://good.com', 'chrome://version', 'brave://*'],
			headless=True,
			user_data_dir=None,
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Should match domains ending with google.com
		assert watchdog._is_url_allowed('https://google.com') is True
		assert watchdog._is_url_allowed('https://www.google.com') is True
		assert (
			watchdog._is_url_allowed('https://evilgood.com') is False
		)  # make sure we dont allow *good.com patterns, only *.good.com

		# Should match domains starting with wiki
		assert watchdog._is_url_allowed('http://wiki.org') is False
		assert watchdog._is_url_allowed('https://wiki.org') is True

		# Should not match internal domains because scheme was not provided
		assert watchdog._is_url_allowed('chrome://google.com') is False
		assert watchdog._is_url_allowed('chrome://abc.google.com') is False

		# Test browser internal URLs
		assert watchdog._is_url_allowed('chrome://settings') is False
		assert watchdog._is_url_allowed('chrome://version') is True
		assert watchdog._is_url_allowed('chrome-extension://version/') is False
		assert watchdog._is_url_allowed('brave://anything/') is True
		assert watchdog._is_url_allowed('about:blank') is True
		assert watchdog._is_url_allowed('chrome://new-tab-page/') is True
		assert watchdog._is_url_allowed('chrome://new-tab-page') is True

		# Test security for glob patterns (authentication credentials bypass attempts)
		# These should all be detected as malicious despite containing allowed domain patterns
		assert watchdog._is_url_allowed('https://allowed.example.com:password@notallowed.com') is False
		assert watchdog._is_url_allowed('https://subdomain.example.com@evil.com') is False
		assert watchdog._is_url_allowed('https://sub.example.com%20@malicious.org') is False
		assert watchdog._is_url_allowed('https://anygoogle.com@evil.org') is False

	def test_glob_pattern_edge_cases(self):
		"""Test edge cases for glob pattern matching to ensure proper behavior."""
		from bubus import EventBus

		from browser_use.browser.security_watchdog import SecurityWatchdog

		# Test with domains containing glob pattern in the middle
		browser_profile = BrowserProfile(allowed_domains=['*.google.com', 'https://wiki.org'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Verify that 'wiki*' pattern doesn't match domains that merely contain 'wiki' in the middle
		assert watchdog._is_url_allowed('https://notawiki.com') is False
		assert watchdog._is_url_allowed('https://havewikipages.org') is False
		assert watchdog._is_url_allowed('https://my-wiki-site.com') is False

		# Verify that '*google.com' doesn't match domains that have 'google' in the middle
		assert watchdog._is_url_allowed('https://mygoogle.company.com') is False

		# Create context with potentially risky glob pattern that demonstrates security concerns
		browser_profile = BrowserProfile(allowed_domains=['*.google.com', '*.google.co.uk'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Should match legitimate Google domains
		assert watchdog._is_url_allowed('https://www.google.com') is True
		assert watchdog._is_url_allowed('https://mail.google.co.uk') is True

		# Shouldn't match potentially malicious domains with a similar structure
		# This demonstrates why the previous pattern was risky and why it's now rejected
		assert watchdog._is_url_allowed('https://www.google.evil.com') is False
