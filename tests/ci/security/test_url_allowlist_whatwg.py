"""Regression test for GHSA-wcqc-h395-9rpp: WHATWG backslash normalization in URL allowlist."""

from types import SimpleNamespace
import unittest

from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog


class TestUrlAllowlistWhatwg(unittest.TestCase):
	def setUp(self):
		profile = SimpleNamespace(
			allowed_domains={'allowed-domain.example'},
			prohibited_domains=None,
			block_ip_addresses=False,
		)
		session = SimpleNamespace(browser_profile=profile)
		self.watchdog = SecurityWatchdog.model_construct(
			event_bus=None,
			browser_session=session,
		)

	def test_backslash_parser_discrepancy_rejected(self):
		# http://evil-domain.example\@allowed-domain.example/
		# Under WHATWG / Chromium, this navigates to evil-domain.example
		crafted_url = 'http://evil-domain.example\\@allowed-domain.example/'
		self.assertFalse(
			self.watchdog._is_url_allowed(crafted_url),
			'Crafted URL with backslash bypass was incorrectly allowed',
		)

	def test_whitespace_prefixed_crafted_url_rejected(self):
		# Leading space, tab, or newline before scheme should not evade normalization
		for prefix in [' ', '   ', '\t', '\n', ' \t ']:
			crafted_url = f'{prefix}http://evil-domain.example\\@allowed-domain.example/'
			self.assertFalse(
				self.watchdog._is_url_allowed(crafted_url),
				f'Whitespace-prefixed crafted URL ({prefix!r}) was incorrectly allowed',
			)

	def test_legitimate_allowed_domain_accepted(self):
		normal_url = 'https://allowed-domain.example/some/path?param=value'
		self.assertTrue(
			self.watchdog._is_url_allowed(normal_url),
			'Legitimate URL on allowed domain should be accepted',
		)

	def test_prohibited_domain_with_backslash_blocked(self):
		profile = SimpleNamespace(
			allowed_domains=None,
			prohibited_domains={'evil-domain.example'},
			block_ip_addresses=False,
		)
		session = SimpleNamespace(browser_profile=profile)
		watchdog = SecurityWatchdog.model_construct(
			event_bus=None,
			browser_session=session,
		)
		crafted_url = 'http://evil-domain.example\\@allowed-domain.example/'
		self.assertFalse(
			watchdog._is_url_allowed(crafted_url),
			'URL targeting prohibited domain with backslash bypass was incorrectly allowed',
		)


if __name__ == '__main__':
	unittest.main()
