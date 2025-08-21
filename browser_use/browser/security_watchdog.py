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
		"""Check if navigated URL is allowed and close tab if not."""
		# Check if the navigated URL is allowed (in case of redirects)
		if not self._is_url_allowed(event.url):
			self.logger.warning(f'⛔️ Navigation to non-allowed URL detected: {event.url}')

			# Dispatch browser error
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='NavigationBlocked',
					message=f'Navigation to non-allowed URL: {event.url}',
					details={'url': event.url, 'target_id': event.target_id},
				)
			)

			# Close the target that navigated to the disallowed URL
			try:
				await self.browser_session._cdp_close_page(event.target_id)
				self.logger.info(f'⛔️ Closed target with non-allowed URL: {event.url}')
			except Exception as e:
				self.logger.error(f'⛔️ Failed to close target with non-allowed URL: {type(e).__name__} {e}')

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

	def _log_glob_warning(self) -> None:
		"""Log a warning about glob patterns in allowed_domains."""
		global _GLOB_WARNING_SHOWN
		if not _GLOB_WARNING_SHOWN:
			_GLOB_WARNING_SHOWN = True
			self.logger.warning(
				'⚠️ Using glob patterns in allowed_domains. '
				'Note: Patterns like "*.example.com" will match both subdomains AND the main domain.'
			)

	def _is_url_allowed(self, url: str) -> bool:
		"""Check if a URL is allowed based on the allowed_domains configuration.

		Args:
			url: The URL to check

		Returns:
			True if the URL is allowed, False otherwise
		"""
		# If no allowed_domains specified, allow all URLs
		if not self.browser_session.browser_profile.allowed_domains:
			return True

		# Always allow internal browser targets
		if url in ['about:blank', 'chrome://new-tab-page/', 'chrome://new-tab-page', 'chrome://newtab/']:
			return True

		# Parse the URL to extract components
		from urllib.parse import urlparse

		try:
			parsed = urlparse(url)
		except Exception:
			# Invalid URL
			return False

		# Get the actual host (domain)
		host = parsed.hostname
		if not host:
			return False

		# Full URL for matching (scheme + host)
		full_url_pattern = f'{parsed.scheme}://{host}'

		# Check each allowed domain pattern
		for pattern in self.browser_session.browser_profile.allowed_domains:
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
						if parsed.scheme in ['http', 'https']:
							return True
				elif pattern.endswith('/*'):
					# Pattern like brave://* should match any brave:// URL
					prefix = pattern[:-1]  # Remove the * at the end
					if url.startswith(prefix):
						return True
				else:
					# Use fnmatch for other glob patterns
					if fnmatch.fnmatch(host, pattern):
						return True
			else:
				# Exact match
				if pattern.startswith(('http://', 'https://', 'chrome://', 'brave://', 'file://')):
					# Full URL pattern
					if url.startswith(pattern):
						return True
				else:
					# Domain-only pattern
					if host == pattern:
						return True

		return False
