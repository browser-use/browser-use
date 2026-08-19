"""
Comprehensive tests for IP address blocking in SecurityWatchdog.

Tests cover IPv4, IPv6, localhost, private networks, edge cases, and interactions
with allowed_domains and prohibited_domains configurations.
"""

from bubus import EventBus

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog


class TestIPv4Blocking:
	"""Test blocking of IPv4 addresses."""

	def test_block_public_ipv4_addresses(self):
		"""Test that public IPv4 addresses are blocked when block_ip_addresses=True."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Public IPv4 addresses should be blocked
		assert watchdog._is_url_allowed('http://180.1.1.1/supersafe.txt') is False
		assert watchdog._is_url_allowed('https://8.8.8.8/') is False
		assert watchdog._is_url_allowed('http://1.1.1.1:8080/api') is False
		assert watchdog._is_url_allowed('https://142.250.185.46/search') is False
		assert watchdog._is_url_allowed('http://93.184.216.34/') is False

	def test_block_private_ipv4_networks(self):
		"""Test that private network IPv4 addresses are blocked."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Private network ranges (RFC 1918)
		assert watchdog._is_url_allowed('http://192.168.1.1/') is False
		assert watchdog._is_url_allowed('http://192.168.0.100/admin') is False
		assert watchdog._is_url_allowed('http://10.0.0.1/') is False
		assert watchdog._is_url_allowed('http://10.255.255.255/') is False
		assert watchdog._is_url_allowed('http://172.16.0.1/') is False
		assert watchdog._is_url_allowed('http://172.31.255.254/') is False

	def test_block_localhost_ipv4(self):
		"""Test that localhost IPv4 addresses are blocked."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Localhost/loopback addresses
		assert watchdog._is_url_allowed('http://127.0.0.1/') is False
		assert watchdog._is_url_allowed('http://127.0.0.1:8080/') is False
		assert watchdog._is_url_allowed('https://127.0.0.1:3000/api/test') is False
		assert watchdog._is_url_allowed('http://127.1.2.3/') is False  # Any 127.x.x.x

	def test_block_ipv4_with_ports_and_paths(self):
		"""Test that IPv4 addresses with ports and paths are blocked."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# With various ports
		assert watchdog._is_url_allowed('http://8.8.8.8:80/') is False
		assert watchdog._is_url_allowed('https://8.8.8.8:443/') is False
		assert watchdog._is_url_allowed('http://192.168.1.1:8080/') is False
		assert watchdog._is_url_allowed('http://10.0.0.1:3000/api') is False

		# With paths and query strings
		assert watchdog._is_url_allowed('http://1.2.3.4/path/to/resource') is False
		assert watchdog._is_url_allowed('http://5.6.7.8/api?key=value') is False
		assert watchdog._is_url_allowed('https://9.10.11.12/path/to/file.html#anchor') is False

	def test_allow_ipv4_when_blocking_disabled(self):
		"""Test that IPv4 addresses are allowed when block_ip_addresses=False (default)."""
		browser_profile = BrowserProfile(block_ip_addresses=False, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# All IP addresses should be allowed when blocking is disabled
		assert watchdog._is_url_allowed('http://180.1.1.1/supersafe.txt') is True
		assert watchdog._is_url_allowed('http://192.168.1.1/') is True
		assert watchdog._is_url_allowed('http://127.0.0.1:8080/') is True
		assert watchdog._is_url_allowed('http://8.8.8.8/') is True


class TestIPv6Blocking:
	"""Test blocking of IPv6 addresses."""

	def test_block_ipv6_addresses(self):
		"""Test that IPv6 addresses are blocked when block_ip_addresses=True."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Public IPv6 addresses (with brackets as per URL standard)
		assert watchdog._is_url_allowed('http://[2001:db8::1]/') is False
		assert watchdog._is_url_allowed('https://[2001:4860:4860::8888]/') is False
		assert watchdog._is_url_allowed('http://[2606:4700:4700::1111]/path') is False
		assert watchdog._is_url_allowed('https://[2001:db8:85a3::8a2e:370:7334]/api') is False

	def test_block_ipv6_localhost(self):
		"""Test that IPv6 localhost addresses are blocked."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# IPv6 loopback
		assert watchdog._is_url_allowed('http://[::1]/') is False
		assert watchdog._is_url_allowed('http://[::1]:8080/') is False
		assert watchdog._is_url_allowed('https://[::1]:3000/api') is False
		assert watchdog._is_url_allowed('http://[0:0:0:0:0:0:0:1]/') is False  # Expanded form

	def test_block_ipv6_with_ports_and_paths(self):
		"""Test that IPv6 addresses with ports and paths are blocked."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# IPv6 with ports
		assert watchdog._is_url_allowed('http://[2001:db8::1]:80/') is False
		assert watchdog._is_url_allowed('https://[2001:db8::1]:443/') is False
		assert watchdog._is_url_allowed('http://[::1]:8080/api') is False

		# IPv6 with paths
		assert watchdog._is_url_allowed('http://[2001:db8::1]/path/to/resource') is False
		assert watchdog._is_url_allowed('https://[2001:db8::1]/api?key=value') is False

	def test_allow_ipv6_when_blocking_disabled(self):
		"""Test that IPv6 addresses are allowed when block_ip_addresses=False."""
		browser_profile = BrowserProfile(block_ip_addresses=False, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# All IPv6 addresses should be allowed
		assert watchdog._is_url_allowed('http://[2001:db8::1]/') is True
		assert watchdog._is_url_allowed('http://[::1]:8080/') is True
		assert watchdog._is_url_allowed('https://[2001:4860:4860::8888]/') is True


class TestDomainNamesStillAllowed:
	"""Test that regular domain names are not affected by IP blocking."""

	def test_domain_names_allowed_with_ip_blocking(self):
		"""Test that domain names continue to work when IP blocking is enabled."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Regular domain names should still be allowed
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('https://www.google.com') is True
		assert watchdog._is_url_allowed('http://subdomain.example.org/path') is True
		assert watchdog._is_url_allowed('https://api.github.com/repos') is True
		assert watchdog._is_url_allowed('http://localhost/') is True  # "localhost" is a domain name, not IP
		assert watchdog._is_url_allowed('http://localhost:8080/api') is True

	def test_domains_with_numbers_allowed(self):
		"""Test that domain names containing numbers are still allowed."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Domains with numbers (but not valid IP addresses)
		assert watchdog._is_url_allowed('https://example123.com') is True
		assert watchdog._is_url_allowed('https://123example.com') is True
		assert watchdog._is_url_allowed('https://server1.example.com') is True
		assert watchdog._is_url_allowed('http://web2.site.org') is True


class TestIPBlockingWithAllowedDomains:
	"""Test interaction between IP blocking and allowed_domains."""

	def test_ip_blocked_even_in_allowed_domains(self):
		"""Test that IPs are blocked even if they're in allowed_domains list."""
		# Note: It doesn't make sense to add IPs to allowed_domains, but if someone does,
		# IP blocking should take precedence
		browser_profile = BrowserProfile(
			block_ip_addresses=True,
			allowed_domains=['example.com', '192.168.1.1'],  # IP in allowlist
			headless=True,
			user_data_dir=None,
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# IP should be blocked despite being in allowed_domains
		assert watchdog._is_url_allowed('http://192.168.1.1/') is False

		# Regular domain should work as expected
		assert watchdog._is_url_allowed('https://example.com') is True

		# Other domains not in allowed_domains should be blocked
		assert watchdog._is_url_allowed('https://other.com') is False

	def test_allowed_domains_with_ip_blocking_enabled(self):
		"""Test that allowed_domains works normally with IP blocking enabled."""
		browser_profile = BrowserProfile(
			block_ip_addresses=True, allowed_domains=['example.com', '*.google.com'], headless=True, user_data_dir=None
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Allowed domains should work
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('https://www.google.com') is True

		# Not allowed domains should be blocked
		assert watchdog._is_url_allowed('https://other.com') is False

		# IPs should be blocked regardless
		assert watchdog._is_url_allowed('http://8.8.8.8/') is False
		assert watchdog._is_url_allowed('http://192.168.1.1/') is False


class TestIPBlockingWithProhibitedDomains:
	"""Test interaction between IP blocking and prohibited_domains."""

	def test_ip_blocked_regardless_of_prohibited_domains(self):
		"""Test that IPs are blocked when IP blocking is on, independent of prohibited_domains."""
		browser_profile = BrowserProfile(
			block_ip_addresses=True, prohibited_domains=['example.com'], headless=True, user_data_dir=None
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# IPs should be blocked due to IP blocking
		assert watchdog._is_url_allowed('http://192.168.1.1/') is False
		assert watchdog._is_url_allowed('http://8.8.8.8/') is False

		# Prohibited domain should be blocked
		assert watchdog._is_url_allowed('https://example.com') is False

		# Other domains should be allowed
		assert watchdog._is_url_allowed('https://other.com') is True

	def test_prohibited_domains_without_ip_blocking(self):
		"""Test that prohibited_domains works normally when IP blocking is disabled."""
		browser_profile = BrowserProfile(
			block_ip_addresses=False, prohibited_domains=['example.com', '8.8.8.8'], headless=True, user_data_dir=None
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Prohibited domain should be blocked
		assert watchdog._is_url_allowed('https://example.com') is False

		# IP in prohibited list should be blocked (by prohibited_domains, not IP blocking)
		assert watchdog._is_url_allowed('http://8.8.8.8/') is False

		# Other IPs should be allowed (IP blocking is off)
		assert watchdog._is_url_allowed('http://192.168.1.1/') is True

		# Other domains should be allowed
		assert watchdog._is_url_allowed('https://other.com') is True


class TestEdgeCases:
	"""Test edge cases and invalid inputs."""

	def test_invalid_urls_handled_gracefully(self):
		"""Test that invalid URLs don't cause crashes."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Invalid URLs should return False
		assert watchdog._is_url_allowed('not-a-url') is False
		assert watchdog._is_url_allowed('') is False
		assert watchdog._is_url_allowed('http://') is False
		assert watchdog._is_url_allowed('://example.com') is False

	def test_internal_browser_urls_allowed(self):
		"""Test that internal browser URLs are still allowed with IP blocking."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Internal URLs should always be allowed
		assert watchdog._is_url_allowed('about:blank') is True
		assert watchdog._is_url_allowed('chrome://new-tab-page/') is True
		assert watchdog._is_url_allowed('chrome://new-tab-page') is True
		assert watchdog._is_url_allowed('chrome://newtab/') is True

	def test_ipv4_lookalike_domains_allowed(self):
		"""Test that strings that look like IPs but cannot be resolved as IPs by
		the kernel/browser are still treated as domain names and allowed.

		Note: short-form IPv4 strings such as `1.2.3` (which Chromium resolves
		as `1.2.0.3`) ARE recognized as IPs — see TestNonStandardIPv4Representations.
		"""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# These look like IPs but cannot resolve as IPv4 in any form the browser accepts:
		# - 999.999.999.999: out of range for every octet
		# - 1.2.3.4.5: too many octets
		assert watchdog._is_url_allowed('http://999.999.999.999/') is True
		assert watchdog._is_url_allowed('http://1.2.3.4.5/') is True

	def test_different_schemes_with_ips(self):
		"""Test that IP blocking works across different URL schemes."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# HTTP and HTTPS
		assert watchdog._is_url_allowed('http://192.168.1.1/') is False
		assert watchdog._is_url_allowed('https://192.168.1.1/') is False

		# FTP (if browser supports it)
		assert watchdog._is_url_allowed('ftp://192.168.1.1/') is False

		# WebSocket (parsed as regular URL)
		assert watchdog._is_url_allowed('ws://192.168.1.1:8080/') is False
		assert watchdog._is_url_allowed('wss://192.168.1.1:8080/') is False


class TestIsIPAddressHelper:
	"""Test the _is_ip_address helper method directly."""

	def test_valid_ipv4_detection(self):
		"""Test that valid IPv4 addresses are correctly detected."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Valid IPv4 addresses
		assert watchdog._is_ip_address('127.0.0.1') is True
		assert watchdog._is_ip_address('192.168.1.1') is True
		assert watchdog._is_ip_address('8.8.8.8') is True
		assert watchdog._is_ip_address('255.255.255.255') is True
		assert watchdog._is_ip_address('0.0.0.0') is True

	def test_valid_ipv6_detection(self):
		"""Test that valid IPv6 addresses are correctly detected."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Valid IPv6 addresses (without brackets - those are URL-specific)
		assert watchdog._is_ip_address('::1') is True
		assert watchdog._is_ip_address('2001:db8::1') is True
		assert watchdog._is_ip_address('2001:4860:4860::8888') is True
		assert watchdog._is_ip_address('fe80::1') is True
		assert watchdog._is_ip_address('2001:db8:85a3::8a2e:370:7334') is True

	def test_invalid_ip_detection(self):
		"""Test that non-IP strings are correctly identified as not IPs."""
		browser_profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Domain names (not IPs)
		assert watchdog._is_ip_address('example.com') is False
		assert watchdog._is_ip_address('www.google.com') is False
		assert watchdog._is_ip_address('localhost') is False

		# Invalid IPs (rejected by both ipaddress and inet_aton)
		assert watchdog._is_ip_address('999.999.999.999') is False
		assert watchdog._is_ip_address('1.2.3.4.5') is False
		assert watchdog._is_ip_address('not-an-ip') is False
		assert watchdog._is_ip_address('') is False

		# Short-form IPv4 strings (1.2.3 == 1.2.0.3) ARE valid IPs that
		# browsers/kernel resolve — covered by TestNonStandardIPv4Representations.

		# IPs with ports or paths (not valid for the helper - it only checks hostnames)
		assert watchdog._is_ip_address('192.168.1.1:8080') is False
		assert watchdog._is_ip_address('192.168.1.1/path') is False


class TestDefaultBehavior:
	"""Test that default behavior (no IP blocking) is maintained."""

	def test_default_block_ip_addresses_is_false(self):
		"""Test that block_ip_addresses defaults to False."""
		browser_profile = BrowserProfile(headless=True, user_data_dir=None)

		# Default should be False
		assert browser_profile.block_ip_addresses is False

	def test_no_blocking_by_default(self):
		"""Test that IPs are not blocked by default."""
		browser_profile = BrowserProfile(headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# All IPs should be allowed by default
		assert watchdog._is_url_allowed('http://180.1.1.1/supersafe.txt') is True
		assert watchdog._is_url_allowed('http://192.168.1.1/') is True
		assert watchdog._is_url_allowed('http://127.0.0.1:8080/') is True
		assert watchdog._is_url_allowed('http://[::1]/') is True
		assert watchdog._is_url_allowed('https://8.8.8.8/') is True


class TestComplexScenarios:
	"""Test complex real-world scenarios."""

	def test_mixed_configuration_comprehensive(self):
		"""Test a complex configuration with multiple security settings."""
		browser_profile = BrowserProfile(
			block_ip_addresses=True,
			allowed_domains=['example.com', '*.google.com'],
			prohibited_domains=['bad.example.com'],  # Should be ignored when allowlist is set
			headless=True,
			user_data_dir=None,
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Allowed domains should work
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('https://www.google.com') is True
		assert watchdog._is_url_allowed('https://mail.google.com') is True

		# IPs should be blocked
		assert watchdog._is_url_allowed('http://8.8.8.8/') is False
		assert watchdog._is_url_allowed('http://192.168.1.1/') is False

		# Domains not in allowlist should be blocked
		assert watchdog._is_url_allowed('https://other.com') is False

	def test_localhost_development_scenario(self):
		"""Test typical local development scenario."""
		# Developer wants to block external IPs but allow domain names
		browser_profile = BrowserProfile(
			block_ip_addresses=True,
			headless=True,
			user_data_dir=None,  # No domain restrictions
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Domain names should work (including localhost as a name)
		assert watchdog._is_url_allowed('http://localhost:3000/') is True
		assert watchdog._is_url_allowed('http://localhost:8080/api') is True

		# But localhost IP should be blocked
		assert watchdog._is_url_allowed('http://127.0.0.1:3000/') is False

		# External domains should work
		assert watchdog._is_url_allowed('https://api.example.com') is True

		# External IPs should be blocked
		assert watchdog._is_url_allowed('http://8.8.8.8/') is False

	def test_security_hardening_scenario(self):
		"""Test maximum security scenario with IP blocking and domain restrictions."""
		browser_profile = BrowserProfile(
			block_ip_addresses=True,
			allowed_domains=['example.com', 'api.example.com'],
			headless=True,
			user_data_dir=None,
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Only specified domains allowed
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('https://api.example.com') is True

		# IPs blocked
		assert watchdog._is_url_allowed('http://192.168.1.1/') is False

		# Other domains blocked
		assert watchdog._is_url_allowed('https://other.com') is False

		# Even localhost blocked
		assert watchdog._is_url_allowed('http://127.0.0.1/') is False


class TestNonStandardIPv4Representations:
	"""Regression tests for GHSA-xrfv-gg9f-wwjp / GHSA-g27c-8gp4-28cv.

	`ipaddress.ip_address()` only accepts the canonical dotted-quad form, but
	Chromium also resolves decimal, hex, octal, and short-form IPv4 strings.
	Without canonicalization, `block_ip_addresses=True` could be bypassed via:

	  http://2130706433/      → 127.0.0.1 (decimal)
	  http://0x7f000001/      → 127.0.0.1 (hex)
	  http://0177.0.0.1/      → 127.0.0.1 (octal)
	  http://127.1/           → 127.0.0.1 (short-form)
	  http://127.0.1/         → 127.0.0.1 (short-form)
	"""

	def _watchdog(self) -> SecurityWatchdog:
		profile = BrowserProfile(block_ip_addresses=True, headless=True, user_data_dir=None)
		session = BrowserSession(browser_profile=profile)
		return SecurityWatchdog(browser_session=session, event_bus=EventBus())

	def test_decimal_ipv4_blocked(self):
		"""Decimal integer IPv4 strings (browser-accepted) must be blocked."""
		watchdog = self._watchdog()
		assert watchdog._is_url_allowed('http://2130706433/') is False  # 127.0.0.1
		assert watchdog._is_url_allowed('http://3232235521/') is False  # 192.168.0.1

	def test_hex_ipv4_blocked(self):
		"""Hex IPv4 strings (browser-accepted) must be blocked."""
		watchdog = self._watchdog()
		assert watchdog._is_url_allowed('http://0x7f000001/') is False  # 127.0.0.1
		assert watchdog._is_url_allowed('http://0x7F.0x0.0x0.0x1/') is False

	def test_octal_ipv4_blocked(self):
		"""Octal IPv4 strings (browser-accepted) must be blocked."""
		watchdog = self._watchdog()
		assert watchdog._is_url_allowed('http://0177.0.0.1/') is False  # 127.0.0.1

	def test_short_form_ipv4_blocked(self):
		"""Short-form IPv4 strings (browser-accepted) must be blocked."""
		watchdog = self._watchdog()
		assert watchdog._is_url_allowed('http://127.1/') is False
		assert watchdog._is_url_allowed('http://127.0.1/') is False
		assert watchdog._is_url_allowed('http://10.1/') is False

	def test_lookalike_domains_still_allowed(self):
		"""Hostnames that look IP-ish but are not (e.g. embedded labels) must
		remain unaffected — only browser-resolvable IP forms should be blocked."""
		watchdog = self._watchdog()
		# Real domains, not IPs — should not be incorrectly blocked.
		assert watchdog._is_url_allowed('http://127.0.0.1.evil.com/') is True
		assert watchdog._is_url_allowed('http://2130706433.evil.com/') is True
		assert watchdog._is_url_allowed('http://example.com/') is True

	def test_non_standard_forms_allowed_when_blocking_disabled(self):
		"""Without block_ip_addresses, non-standard IPv4 strings are not blocked."""
		profile = BrowserProfile(block_ip_addresses=False, headless=True, user_data_dir=None)
		session = BrowserSession(browser_profile=profile)
		watchdog = SecurityWatchdog(browser_session=session, event_bus=EventBus())
		assert watchdog._is_url_allowed('http://2130706433/') is True
		assert watchdog._is_url_allowed('http://0x7f000001/') is True

	def test_non_standard_forms_blocked_inside_allowed_domains(self):
		"""block_ip_addresses must override allowed_domains for non-standard forms
		just as it does for the canonical form."""
		profile = BrowserProfile(
			block_ip_addresses=True,
			allowed_domains=['*'],
			headless=True,
			user_data_dir=None,
		)
		session = BrowserSession(browser_profile=profile)
		watchdog = SecurityWatchdog(browser_session=session, event_bus=EventBus())
		# Even with '*' allowlist, the IP block must still fire.
		assert watchdog._is_url_allowed('http://2130706433/') is False
		assert watchdog._is_url_allowed('http://0x7f000001/') is False
		# Sanity: legitimate domains still allowed.
		assert watchdog._is_url_allowed('https://example.com/') is True

	def test_malformed_unicode_hostnames_do_not_crash_classifier(self):
		"""Hostnames with lone surrogates (e.g. `\\udcff` from URL-decoded
		malformed UTF-8) must not crash `_is_ip_address` — `socket.inet_aton`
		raises `UnicodeEncodeError` (not `OSError`) for surrogates, and the
		classifier must treat that as "not an IP" rather than propagating.

		Pre-existing defensive behavior in the original code (caught
		`Exception`) — must be preserved when extending with `inet_aton`.
		"""
		watchdog = self._watchdog()
		# Lone surrogates — common in URLs containing percent-encoded malformed UTF-8.
		assert watchdog._is_ip_address('\udcff') is False
		assert watchdog._is_ip_address('\ud800') is False
		assert watchdog._is_ip_address('caf\udce9.local') is False
		assert watchdog._is_ip_address('\udcff.example.com') is False

	def test_percent_encoded_ipv4_blocked(self):
		"""Percent-encoded hostnames that decode to IPs must be blocked.

		Chromium percent-decodes the host before resolving — so
		`http://%30x7f000001/` decodes to `0x7f000001` → `127.0.0.1`, and
		`http://%31%32%37.0.0.1/` decodes to `127.0.0.1`. Without
		percent-decoding inside the classifier, the IP block is bypassed
		whenever the URL contains any `%`-encoded host bytes.
		"""
		watchdog = self._watchdog()
		# Mixed encoding: %30 = '0', rest literal → '0x7f000001'
		assert watchdog._is_url_allowed('http://%30x7f000001/') is False
		# Fully encoded canonical form: %31%32%37 = '127'
		assert watchdog._is_url_allowed('http://%31%32%37.0.0.1/') is False
		# Fully encoded decimal form: → '2130706433'
		assert watchdog._is_url_allowed('http://%32%31%33%30%37%30%36%34%33%33/') is False
		# Direct classifier checks for the same decoded forms.
		assert watchdog._is_ip_address('%30x7f000001') is True
		assert watchdog._is_ip_address('%31%32%37.0.0.1') is True
		assert watchdog._is_ip_address('%32%31%33%30%37%30%36%34%33%33') is True

	def test_malformed_percent_encoding_does_not_crash(self):
		"""Hostnames with malformed `%` escapes must not crash the classifier."""
		watchdog = self._watchdog()
		# `unquote` leaves bad `%`-sequences as-is; we must still treat the
		# result as a non-IP rather than blowing up.
		assert watchdog._is_ip_address('%') is False
		assert watchdog._is_ip_address('%zz') is False
		assert watchdog._is_ip_address('%2') is False

	def test_unicode_normalized_ipv4_blocked(self):
		"""Hostnames using fullwidth, circled, or other Unicode digit variants
		that NFKC/IDNA-normalize to ASCII IPv4 literals must be blocked.

		WHATWG URL canonicalization maps `１２７.０.０.１` (fullwidth digits),
		`０x7f000001` (fullwidth zero + ASCII hex), and `①②⑦.⓪.⓪.①` (circled
		digits) all to `127.0.0.1`. Without NFKC normalization in the
		classifier, the new non-standard IPv4 blocking can be bypassed with
		any equivalent Unicode digit form.
		"""
		watchdog = self._watchdog()
		# Fullwidth digits (U+FF10..U+FF19) — NFKC → ASCII digits.
		assert watchdog._is_url_allowed('http://１２７.０.０.１/') is False
		# Fullwidth zero + ASCII hex 7f000001.
		assert watchdog._is_url_allowed('http://０x7f000001/') is False
		# Circled digits (U+2460+, U+24EA for zero).
		assert watchdog._is_url_allowed('http://①②⑦.⓪.⓪.①/') is False
		# Direct classifier checks.
		assert watchdog._is_ip_address('１２７.０.０.１') is True
		assert watchdog._is_ip_address('０x7f000001') is True
		assert watchdog._is_ip_address('①②⑦.⓪.⓪.①') is True

	def test_idn_domains_not_misclassified_as_ip(self):
		"""Defense against false positives from the new normalization step:
		legitimate IDN domains (Unicode letters / punycode) MUST NOT be
		classified as IPs after NFKC."""
		watchdog = self._watchdog()
		assert watchdog._is_ip_address('café.example') is False
		assert watchdog._is_ip_address('xn--caf-dma.example') is False
		assert watchdog._is_ip_address('日本.example') is False
		assert watchdog._is_ip_address('xn--wgv71a.example') is False

	def test_idna_dot_separators_blocked(self):
		"""Per RFC 3490 / UTS46, four code points act as label separators in
		IDNA processing — `.` (U+002E), `。` (U+3002 IDEOGRAPHIC FULL STOP),
		`．` (U+FF0E FULLWIDTH FULL STOP), `｡` (U+FF61 HALFWIDTH IDEOGRAPHIC
		FULL STOP). WHATWG URL parsing maps all four to `.` before resolution,
		so `http://127。0。0。1/` etc. reach 127.0.0.1.

		NFKC alone is insufficient — it maps U+FF0E → U+002E and U+FF61 →
		U+3002, but leaves U+3002 (the most common one) untouched. Classifier
		must additionally fold U+3002 and U+FF61 to U+002E before IP parsing.
		"""
		watchdog = self._watchdog()
		# All four dot variants must result in the IP being blocked.
		assert watchdog._is_url_allowed('http://127。0。0。1/') is False  # U+3002
		assert watchdog._is_url_allowed('http://127｡0｡0｡1/') is False  # U+FF61
		assert watchdog._is_url_allowed('http://127．0．0．1/') is False  # U+FF0E
		# Combined with circled-digit normalization.
		assert watchdog._is_url_allowed('http://①②⑦。⓪。⓪。①/') is False
		# Direct classifier checks.
		assert watchdog._is_ip_address('127。0。0。1') is True
		assert watchdog._is_ip_address('127｡0｡0｡1') is True
		assert watchdog._is_ip_address('127．0．0．1') is True
