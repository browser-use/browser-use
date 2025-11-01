"""Security watchdog for enforcing URL access policies."""

from typing import TYPE_CHECKING, ClassVar

from bubus import BaseEvent

from browser_use.browser.events import (
	BrowserErrorEvent,
	NavigateToUrlEvent,
	NavigationCompleteEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog

if TYPE_CHECKING:
	pass

# Track if we've shown the glob warning
_GLOB_WARNING_SHOWN = False


class SecurityWatchdog(BaseWatchdog):
	"""Monitors and enforces security policies for URL access."""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		NavigateToUrlEvent,
		NavigationCompleteEvent,
		TabCreatedEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent]]] = [
		BrowserErrorEvent,
	]

	async def on_NavigateToUrlEvent(self, event: NavigateToUrlEvent) -> None:
		"""Check if navigation URL is allowed before navigation starts."""
		# Security check BEFORE navigation
		if not self._is_url_allowed(event.url):
			self.logger.warning(f'⛔️ Blocking navigation to disallowed URL: {event.url}')
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='NavigationBlocked',
					message=f'Navigation blocked to disallowed URL: {event.url}',
					details={'url': event.url, 'reason': 'not_in_allowed_domains'},
				)
			)
			# Stop event propagation by raising exception
			raise ValueError(f'Navigation to {event.url} blocked by security policy')

	async def on_NavigationCompleteEvent(self, event: NavigationCompleteEvent) -> None:
		"""Check if navigated URL is allowed (catches redirects to blocked domains)."""
		# Check if the navigated URL is allowed (in case of redirects)
		if not self._is_url_allowed(event.url):
			self.logger.warning(f'⛔️ Navigation to non-allowed URL detected: {event.url}')

			# Dispatch browser error
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='NavigationBlocked',
					message=f'Navigation blocked to non-allowed URL: {event.url} - redirecting to about:blank',
					details={'url': event.url, 'target_id': event.target_id},
				)
			)
			# Navigate to about:blank to keep session alive
			# Agent will see the error and can continue with other tasks
			try:
				session = await self.browser_session.get_or_create_cdp_session(target_id=event.target_id)
				await session.cdp_client.send.Page.navigate(params={'url': 'about:blank'}, session_id=session.session_id)
				self.logger.info(f'⛔️ Navigated to about:blank after blocked URL: {event.url}')
			except Exception as e:
				pass
				self.logger.error(f'⛔️ Failed to navigate to about:blank: {type(e).__name__} {e}')

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Check if new tab URL is allowed."""
		if not self._is_url_allowed(event.url):
			self.logger.warning(f'⛔️ New tab created with disallowed URL: {event.url}')

			# Dispatch error and try to close the tab
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='TabCreationBlocked',
					message=f'Tab created with non-allowed URL: {event.url}',
					details={'url': event.url, 'target_id': event.target_id},
				)
			)

			# Try to close the offending tab
			try:
				await self.browser_session._cdp_close_page(event.target_id)
				self.logger.info(f'⛔️ Closed new tab with non-allowed URL: {event.url}')
			except Exception as e:
				self.logger.error(f'⛔️ Failed to close new tab with non-allowed URL: {type(e).__name__} {e}')

	def _is_root_domain(self, domain: str) -> bool:
		"""Check if a domain is a root domain (no subdomain present).

		Simple heuristic: only add www for domains with exactly 1 dot (domain.tld).
		For complex cases like country TLDs or subdomains, users should configure explicitly.

		Args:
			domain: The domain to check

		Returns:
			True if it's a simple root domain, False otherwise
		"""
		# Skip if it contains wildcards or protocol
		if '*' in domain or '://' in domain:
			return False

		return domain.count('.') == 1

	def _log_glob_warning(self) -> None:
		"""Log a warning about glob patterns in allowed_domains."""
		global _GLOB_WARNING_SHOWN
		if not _GLOB_WARNING_SHOWN:
			_GLOB_WARNING_SHOWN = True
			self.logger.warning(
				'⚠️ Using glob patterns in allowed_domains. '
				'Note: Patterns like "*.example.com" will match both subdomains AND the main domain.'
			)

	def _get_domain_variants(self, host: str) -> tuple[str, str]:
		"""Get both variants of a domain (with and without www prefix).

		Args:
			host: The hostname to process

		Returns:
			Tuple of (original_host, variant_host)
			- If host starts with www., variant is without www.
			- Otherwise, variant is with www. prefix
		"""
		if host.startswith('www.'):
			return (host, host[4:])  # ('www.example.com', 'example.com')
		else:
			return (host, f'www.{host}')  # ('example.com', 'www.example.com')

	def _is_ip_address(self, host: str) -> bool:
		"""Check if a hostname is an IP address (IPv4 or IPv6).

		Args:
			host: The hostname to check

		Returns:
			True if the host is an IP address, False otherwise
		"""
		import ipaddress

		try:
			# Try to parse as IP address (handles both IPv4 and IPv6)
			ipaddress.ip_address(host)
			return True
		except ValueError:
			return False
		except Exception:
			return False

	def _is_url_allowed(self, url: str) -> bool:
		"""Check if a URL is allowed based on the allowed_domains configuration.

		Args:
			url: The URL to check

		Returns:
			True if the URL is allowed, False otherwise
		"""

		# Always allow internal browser targets (before any other checks)
		if url in ['about:blank', 'chrome://new-tab-page/', 'chrome://new-tab-page', 'chrome://newtab/']:
			return True

		# Parse the URL to extract components
		from urllib.parse import urlparse

		try:
			parsed = urlparse(url)
		except Exception:
			# Invalid URL
			return False

		# Allow data: and blob: URLs (they don't have hostnames)
		if parsed.scheme in ['data', 'blob']:
			return True

		# Get the actual host (domain)
		host = parsed.hostname
		if not host:
			return False

		# Check if IP addresses should be blocked (before domain checks)
		if self.browser_session.browser_profile.block_ip_addresses:
			if self._is_ip_address(host):
				return False

		# If no allowed_domains specified, allow all URLs
		if (
			not self.browser_session.browser_profile.allowed_domains
			and not self.browser_session.browser_profile.prohibited_domains
		):
			return True

		# Check allowed domains (fast path for sets, slow path for lists with patterns)
		if self.browser_session.browser_profile.allowed_domains:
			allowed_domains = self.browser_session.browser_profile.allowed_domains

			if isinstance(allowed_domains, set):
				# Fast path: O(1) exact hostname match - check both www and non-www variants
				host_variant, host_alt = self._get_domain_variants(host)
				return host_variant in allowed_domains or host_alt in allowed_domains
			else:
				# Slow path: O(n) pattern matching for lists
				for pattern in allowed_domains:
					if self._is_url_match(url, host, parsed.scheme, pattern):
						return True
				return False

		# Check prohibited domains (fast path for sets, slow path for lists with patterns)
		if self.browser_session.browser_profile.prohibited_domains:
			prohibited_domains = self.browser_session.browser_profile.prohibited_domains

			if isinstance(prohibited_domains, set):
				# Fast path: O(1) exact hostname match - check both www and non-www variants
				host_variant, host_alt = self._get_domain_variants(host)
				return host_variant not in prohibited_domains and host_alt not in prohibited_domains
			else:
				# Slow path: O(n) pattern matching for lists
				for pattern in prohibited_domains:
					if self._is_url_match(url, host, parsed.scheme, pattern):
						return False
				return True

		return True

	def _is_url_match(self, url: str, host: str, scheme: str, pattern: str) -> bool:
		"""Check if a URL matches a pattern."""

		# Full URL for matching (scheme + host)
		full_url_pattern = f'{scheme}://{host}'

		# Handle glob patterns
		if '*' in pattern:
			self._log_glob_warning()
			import fnmatch

			# Check if pattern matches the host
			if pattern.startswith('*.'):
				# Pattern like *.example.com should match subdomains and main domain
				domain_part = pattern[2:]  # Remove *.
				if host == domain_part or host.endswith('.' + domain_part):
					# Only match http/https URLs for domain-only patterns
					if scheme in ['http', 'https']:
						return True
			elif pattern.endswith('/*'):
				# Pattern like brave://* should match any brave:// URL
				prefix = pattern[:-1]  # Remove the * at the end
				if url.startswith(prefix):
					return True
			else:
				# Use fnmatch for other glob patterns
				if fnmatch.fnmatch(
					full_url_pattern if '://' in pattern else host,
					pattern,
				):
					return True
		else:
			# Exact match
			if '://' in pattern:
				# Full URL pattern
				if url.startswith(pattern):
					return True
			else:
				# Domain-only pattern (case-insensitive comparison)
				if host.lower() == pattern.lower():
					return True
				# If pattern is a root domain, also check www subdomain
				if self._is_root_domain(pattern) and host.lower() == f'www.{pattern.lower()}':
					return True

		return False
