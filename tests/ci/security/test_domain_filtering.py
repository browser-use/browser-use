from browser_use.browser import BrowserProfile, BrowserSession


class TestUrlAllowlistSecurity:
	"""Tests for URL allowlist security bypass prevention and URL allowlist glob pattern matching."""

	def test_authentication_bypass_prevention(self):
		"""Test that the URL allowlist cannot be bypassed using authentication credentials."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

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

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

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
			allowed_domains=[
				'*.google.com',
				'https://wiki.org',
				'https://good.com',
				'https://*.test.com',
				'chrome://version',
				'brave://*',
			],
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

		# Test pattern matching
		assert watchdog._is_url_allowed('https://www.test.com') is True
		assert watchdog._is_url_allowed('https://www.testx.com') is False

	def test_glob_pattern_edge_cases(self):
		"""Test edge cases for glob pattern matching to ensure proper behavior."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

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

	def test_automatic_www_subdomain_addition(self):
		"""Test that root domains automatically allow www subdomain."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		# Test with simple root domains
		browser_profile = BrowserProfile(allowed_domains=['example.com', 'test.org'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Root domain should allow itself
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('https://test.org') is True

		# Root domain should automatically allow www subdomain
		assert watchdog._is_url_allowed('https://www.example.com') is True
		assert watchdog._is_url_allowed('https://www.test.org') is True

		# Should not allow other subdomains
		assert watchdog._is_url_allowed('https://mail.example.com') is False
		assert watchdog._is_url_allowed('https://sub.test.org') is False

		# Should not allow unrelated domains
		assert watchdog._is_url_allowed('https://notexample.com') is False
		assert watchdog._is_url_allowed('https://www.notexample.com') is False

	def test_www_subdomain_not_added_for_country_tlds(self):
		"""Test www subdomain is NOT automatically added for country-specific TLDs (2+ dots)."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		# Test with country-specific TLDs - these should NOT get automatic www
		browser_profile = BrowserProfile(
			allowed_domains=['example.co.uk', 'test.com.au', 'site.co.jp'], headless=True, user_data_dir=None
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Root domains should work exactly as specified
		assert watchdog._is_url_allowed('https://example.co.uk') is True
		assert watchdog._is_url_allowed('https://test.com.au') is True
		assert watchdog._is_url_allowed('https://site.co.jp') is True

		# www subdomains should NOT work automatically (user must specify explicitly)
		assert watchdog._is_url_allowed('https://www.example.co.uk') is False
		assert watchdog._is_url_allowed('https://www.test.com.au') is False
		assert watchdog._is_url_allowed('https://www.site.co.jp') is False

		# Other subdomains should not work
		assert watchdog._is_url_allowed('https://mail.example.co.uk') is False
		assert watchdog._is_url_allowed('https://api.test.com.au') is False

	def test_www_subdomain_not_added_for_existing_subdomains(self):
		"""Test that www is not automatically added for domains that already have subdomains."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		# Test with existing subdomains - should NOT get automatic www
		browser_profile = BrowserProfile(allowed_domains=['mail.example.com', 'api.test.org'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Exact subdomain should work
		assert watchdog._is_url_allowed('https://mail.example.com') is True
		assert watchdog._is_url_allowed('https://api.test.org') is True

		# www should NOT be automatically added to subdomains
		assert watchdog._is_url_allowed('https://www.mail.example.com') is False
		assert watchdog._is_url_allowed('https://www.api.test.org') is False

		# Root domains should not work either
		assert watchdog._is_url_allowed('https://example.com') is False
		assert watchdog._is_url_allowed('https://test.org') is False

	def test_www_subdomain_not_added_for_wildcard_patterns(self):
		"""Test that www is not automatically added for wildcard patterns."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		# Test with wildcard patterns - should NOT get automatic www logic
		browser_profile = BrowserProfile(allowed_domains=['*.example.com'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Wildcard should match everything including root and www
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('https://www.example.com') is True
		assert watchdog._is_url_allowed('https://mail.example.com') is True

	def test_www_subdomain_not_added_for_url_patterns(self):
		"""Test that www is not automatically added for full URL patterns."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		# Test with full URL patterns - should NOT get automatic www logic
		browser_profile = BrowserProfile(
			allowed_domains=['https://example.com', 'http://test.org'], headless=True, user_data_dir=None
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Exact URL should work
		assert watchdog._is_url_allowed('https://example.com/path') is True
		assert watchdog._is_url_allowed('http://test.org/page') is True

		# www should NOT be automatically added for full URL patterns
		assert watchdog._is_url_allowed('https://www.example.com') is False
		assert watchdog._is_url_allowed('http://www.test.org') is False

	def test_is_root_domain_helper(self):
		"""Test the _is_root_domain helper method logic."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		browser_profile = BrowserProfile(allowed_domains=['example.com'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Simple root domains (1 dot) - should return True
		assert watchdog._is_root_domain('example.com') is True
		assert watchdog._is_root_domain('test.org') is True
		assert watchdog._is_root_domain('site.net') is True

		# Subdomains (more than 1 dot) - should return False
		assert watchdog._is_root_domain('www.example.com') is False
		assert watchdog._is_root_domain('mail.example.com') is False
		assert watchdog._is_root_domain('example.co.uk') is False
		assert watchdog._is_root_domain('test.com.au') is False

		# Wildcards - should return False
		assert watchdog._is_root_domain('*.example.com') is False
		assert watchdog._is_root_domain('*example.com') is False

		# Full URLs - should return False
		assert watchdog._is_root_domain('https://example.com') is False
		assert watchdog._is_root_domain('http://test.org') is False

		# Invalid domains - should return False
		assert watchdog._is_root_domain('example') is False
		assert watchdog._is_root_domain('') is False


class TestUrlProhibitlistSecurity:
	"""Tests for URL prohibitlist (blocked domains) behavior and matching semantics."""

	def test_simple_prohibited_domains(self):
		"""Domain-only patterns block exact host and www, but not other subdomains."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		browser_profile = BrowserProfile(prohibited_domains=['example.com', 'test.org'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Block exact and www
		assert watchdog._is_url_allowed('https://example.com') is False
		assert watchdog._is_url_allowed('https://www.example.com') is False
		assert watchdog._is_url_allowed('https://test.org') is False
		assert watchdog._is_url_allowed('https://www.test.org') is False

		# Allow other subdomains when only root is prohibited
		assert watchdog._is_url_allowed('https://mail.example.com') is True
		assert watchdog._is_url_allowed('https://api.test.org') is True

		# Allow unrelated domains
		assert watchdog._is_url_allowed('https://notexample.com') is True

	def test_glob_pattern_prohibited(self):
		"""Wildcard patterns block subdomains and main domain for http/https only."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		browser_profile = BrowserProfile(prohibited_domains=['*.example.com'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Block subdomains and main domain
		assert watchdog._is_url_allowed('https://example.com') is False
		assert watchdog._is_url_allowed('https://www.example.com') is False
		assert watchdog._is_url_allowed('https://mail.example.com') is False

		# Allow other domains
		assert watchdog._is_url_allowed('https://notexample.com') is True

		# Wildcard with domain-only should not apply to non-http(s)
		assert watchdog._is_url_allowed('chrome://abc.example.com') is True

	def test_full_url_prohibited_patterns(self):
		"""Full URL patterns block only matching scheme/host/prefix."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		browser_profile = BrowserProfile(prohibited_domains=['https://wiki.org', 'brave://*'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Scheme-specific blocking
		assert watchdog._is_url_allowed('http://wiki.org') is True
		assert watchdog._is_url_allowed('https://wiki.org') is False
		assert watchdog._is_url_allowed('https://wiki.org/path') is False

		# Internal URL prefix blocking
		assert watchdog._is_url_allowed('brave://anything/') is False
		assert watchdog._is_url_allowed('chrome://settings') is True

	def test_internal_urls_allowed_even_when_prohibited(self):
		"""Internal new-tab/blank URLs are always allowed regardless of prohibited list."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		browser_profile = BrowserProfile(prohibited_domains=['*'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		assert watchdog._is_url_allowed('about:blank') is True
		assert watchdog._is_url_allowed('chrome://new-tab-page/') is True
		assert watchdog._is_url_allowed('chrome://new-tab-page') is True
		assert watchdog._is_url_allowed('chrome://newtab/') is True

	def test_prohibited_ignored_when_allowlist_present(self):
		"""When allowlist is set, prohibited list is ignored by design."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		browser_profile = BrowserProfile(
			allowed_domains=['*.example.com'],
			prohibited_domains=['https://example.com'],
			headless=True,
			user_data_dir=None,
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Allowed by allowlist even though exact URL is in prohibited list
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('https://www.example.com') is True

		# Not in allowlist => blocked (prohibited list is not consulted in this mode)
		assert watchdog._is_url_allowed('https://api.example.com') is True  # wildcard allowlist includes this
		# A domain outside the allowlist should be blocked
		assert watchdog._is_url_allowed('https://notexample.com') is False

	def test_auth_credentials_do_not_cause_false_block(self):
		"""Credentials injection with prohibited domain in username should not block unrelated hosts."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		browser_profile = BrowserProfile(prohibited_domains=['example.com'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Host is malicious.com, should not be blocked just because username contains example.com
		assert watchdog._is_url_allowed('https://example.com:password@malicious.com') is True
		assert watchdog._is_url_allowed('https://example.com@malicious.com') is True
		assert watchdog._is_url_allowed('https://example.com%20@malicious.com') is True
		assert watchdog._is_url_allowed('https://example.com%3A@malicious.com') is True

		# Legitimate credentials to a prohibited host should be blocked
		assert watchdog._is_url_allowed('https://user:password@example.com') is False

	def test_case_insensitive_prohibited_domains(self):
		"""Prohibited domain matching should be case-insensitive."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		browser_profile = BrowserProfile(prohibited_domains=['Example.COM'], headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		assert watchdog._is_url_allowed('https://example.com') is False
		assert watchdog._is_url_allowed('https://WWW.EXAMPLE.COM') is False
		assert watchdog._is_url_allowed('https://mail.example.com') is True


class TestDomainListOptimization:
	"""Tests for domain list optimization (set conversion for large lists)."""

	def test_small_list_keeps_pattern_support(self):
		"""Test that lists < 100 items keep pattern matching support."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		browser_profile = BrowserProfile(
			prohibited_domains=['*.google.com', 'x.com', 'facebook.com'], headless=True, user_data_dir=None
		)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Should still be a list
		assert isinstance(browser_session.browser_profile.prohibited_domains, list)

		# Pattern matching should work
		assert watchdog._is_url_allowed('https://www.google.com') is False
		assert watchdog._is_url_allowed('https://mail.google.com') is False
		assert watchdog._is_url_allowed('https://google.com') is False

		# Exact matches should work
		assert watchdog._is_url_allowed('https://x.com') is False
		assert watchdog._is_url_allowed('https://facebook.com') is False

		# Other domains should be allowed
		assert watchdog._is_url_allowed('https://example.com') is True

	def test_large_list_converts_to_set(self):
		"""Test that lists >= 100 items are converted to sets."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		# Create a list of 100 domains
		large_list = [f'blocked{i}.com' for i in range(100)]

		browser_profile = BrowserProfile(prohibited_domains=large_list, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Should be converted to set
		assert isinstance(browser_session.browser_profile.prohibited_domains, set)
		assert len(browser_session.browser_profile.prohibited_domains) == 100

		# Exact matches should work
		assert watchdog._is_url_allowed('https://blocked0.com') is False
		assert watchdog._is_url_allowed('https://blocked50.com') is False
		assert watchdog._is_url_allowed('https://blocked99.com') is False

		# Other domains should be allowed
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('https://blocked100.com') is True  # Not in list

	def test_www_variant_matching_with_sets(self):
		"""Test that www variants are checked in set-based lookups."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		# Create a list with 100 domains (some with www, some without)
		large_list = [f'site{i}.com' for i in range(50)] + [f'www.domain{i}.org' for i in range(50)]

		browser_profile = BrowserProfile(prohibited_domains=large_list, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Should be converted to set
		assert isinstance(browser_session.browser_profile.prohibited_domains, set)

		# Test www variant matching for domains without www prefix
		assert watchdog._is_url_allowed('https://site0.com') is False
		assert watchdog._is_url_allowed('https://www.site0.com') is False  # Should also be blocked

		# Test www variant matching for domains with www prefix
		assert watchdog._is_url_allowed('https://www.domain0.org') is False
		assert watchdog._is_url_allowed('https://domain0.org') is False  # Should also be blocked

		# Test that unrelated domains are allowed
		assert watchdog._is_url_allowed('https://example.com') is True
		assert watchdog._is_url_allowed('https://www.example.com') is True

	def test_allowed_domains_with_sets(self):
		"""Test that allowed_domains also works with set optimization."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		# Create a large allowlist
		large_list = [f'allowed{i}.com' for i in range(100)]

		browser_profile = BrowserProfile(allowed_domains=large_list, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Should be converted to set
		assert isinstance(browser_session.browser_profile.allowed_domains, set)

		# Allowed domains should work
		assert watchdog._is_url_allowed('https://allowed0.com') is True
		assert watchdog._is_url_allowed('https://www.allowed0.com') is True
		assert watchdog._is_url_allowed('https://allowed99.com') is True

		# Other domains should be blocked
		assert watchdog._is_url_allowed('https://example.com') is False
		assert watchdog._is_url_allowed('https://notallowed.com') is False

	def test_manual_set_input(self):
		"""Test that users can directly provide a set."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		blocked_set = {f'blocked{i}.com' for i in range(50)}

		browser_profile = BrowserProfile(prohibited_domains=blocked_set, headless=True, user_data_dir=None)
		browser_session = BrowserSession(browser_profile=browser_profile)
		event_bus = EventBus()
		watchdog = SecurityWatchdog(browser_session=browser_session, event_bus=event_bus)

		# Should remain a set
		assert isinstance(browser_session.browser_profile.prohibited_domains, set)

		# Should work correctly
		assert watchdog._is_url_allowed('https://blocked0.com') is False
		assert watchdog._is_url_allowed('https://example.com') is True
