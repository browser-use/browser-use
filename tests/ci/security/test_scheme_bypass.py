from browser_use.browser import BrowserProfile, BrowserSession


class TestSchemeBypass:
	"""Tests that non-http/https URL schemes cannot bypass domain restrictions."""

	def _make_watchdog(self, allowed_domains=None, prohibited_domains=None):
		"""Helper to create a SecurityWatchdog with given domain restrictions."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		browser_profile = BrowserProfile(
			allowed_domains=allowed_domains,
			prohibited_domains=prohibited_domains,
			headless=True,
			user_data_dir=None,
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		return SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

	def test_javascript_urls_blocked_with_allowed_domains(self):
		"""javascript: URLs are blocked when allowed_domains is set."""
		watchdog = self._make_watchdog(allowed_domains=['example.com'])

		assert watchdog._is_url_allowed('javascript:alert(1)') is False
		assert watchdog._is_url_allowed('javascript:void(0)') is False
		assert watchdog._is_url_allowed('javascript:document.cookie') is False

	def test_file_urls_blocked_with_allowed_domains(self):
		"""file:// URLs are blocked when allowed_domains is set."""
		watchdog = self._make_watchdog(allowed_domains=['example.com'])

		assert watchdog._is_url_allowed('file:///etc/passwd') is False
		assert watchdog._is_url_allowed('file:///home/user/.ssh/id_rsa') is False
		assert watchdog._is_url_allowed('file://localhost/etc/passwd') is False

	def test_chrome_urls_blocked_except_allowlisted(self):
		"""chrome:// URLs (except the hardcoded internal targets) are blocked."""
		watchdog = self._make_watchdog(allowed_domains=['example.com'])

		# Non-allowlisted chrome:// URLs should be blocked
		assert watchdog._is_url_allowed('chrome://settings') is False
		assert watchdog._is_url_allowed('chrome://flags') is False
		assert watchdog._is_url_allowed('chrome://version') is False
		assert watchdog._is_url_allowed('chrome-extension://abc/popup.html') is False

		# Hardcoded internal targets are always allowed
		assert watchdog._is_url_allowed('chrome://new-tab-page/') is True
		assert watchdog._is_url_allowed('chrome://new-tab-page') is True
		assert watchdog._is_url_allowed('chrome://newtab/') is True
		assert watchdog._is_url_allowed('about:blank') is True

	def test_other_dangerous_schemes_blocked(self):
		"""Other potentially dangerous schemes are blocked when domain restrictions are active."""
		watchdog = self._make_watchdog(allowed_domains=['example.com'])

		assert watchdog._is_url_allowed('data:text/html,<script>alert(1)</script>') is False
		assert watchdog._is_url_allowed('blob:https://example.com/uuid') is False
		assert watchdog._is_url_allowed('about:config') is False
		assert watchdog._is_url_allowed('brave://settings') is False

	def test_http_https_urls_work_normally(self):
		"""http/https URLs still work normally with domain restrictions."""
		watchdog = self._make_watchdog(allowed_domains=['example.com'])

		# Allowed domain works with both schemes
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('http://example.com') is True
		assert watchdog._is_url_allowed('https://example.com/path/page') is True
		assert watchdog._is_url_allowed('https://www.example.com') is True

		# Non-allowed domain is still blocked
		assert watchdog._is_url_allowed('https://evil.com') is False
		assert watchdog._is_url_allowed('http://evil.com') is False

	def test_all_schemes_allowed_without_domain_restrictions(self):
		"""All schemes are allowed when no domain restrictions are configured."""
		watchdog = self._make_watchdog()

		# http/https
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('http://example.com') is True

		# Internal browser targets
		assert watchdog._is_url_allowed('about:blank') is True
		assert watchdog._is_url_allowed('chrome://new-tab-page/') is True

		# data: and blob: URLs
		assert watchdog._is_url_allowed('data:text/html,hello') is True
		assert watchdog._is_url_allowed('blob:https://example.com/uuid') is True

		# file:// URLs
		assert watchdog._is_url_allowed('file:///tmp/test.html') is True

	def test_schemes_blocked_with_prohibited_domains(self):
		"""Non-http/https schemes are also blocked when prohibited_domains is set."""
		watchdog = self._make_watchdog(prohibited_domains=['evil.com'])

		# Non-http/https schemes are blocked
		assert watchdog._is_url_allowed('javascript:alert(1)') is False
		assert watchdog._is_url_allowed('file:///etc/passwd') is False
		assert watchdog._is_url_allowed('chrome://settings') is False
		assert watchdog._is_url_allowed('data:text/html,test') is False

		# http/https still work (non-prohibited domains)
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('http://example.com') is True

		# Prohibited domain is blocked
		assert watchdog._is_url_allowed('https://evil.com') is False

		# Internal browser targets are still allowed
		assert watchdog._is_url_allowed('about:blank') is True
		assert watchdog._is_url_allowed('chrome://new-tab-page/') is True
