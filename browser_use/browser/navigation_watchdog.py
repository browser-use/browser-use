"""Navigation watchdog for monitoring tab lifecycle and agent focus tracking."""

import asyncio
from typing import TYPE_CHECKING, ClassVar

from bubus import BaseEvent
from playwright.async_api import Page
from pydantic import Field

from browser_use.browser.events import (
	AgentFocusChangedEvent,
	BrowserErrorEvent,
	BrowserStoppedEvent,
	NavigateToUrlEvent,
	NavigationCompleteEvent,
	NavigationStartedEvent,
	SwitchTabEvent,
	TabClosedEvent,
	TabCreatedEvent,
	TabsInfoRequestEvent,
	TabsInfoResponseEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.utils import logger

if TYPE_CHECKING:
	pass


class NavigationWatchdog(BaseWatchdog):
	"""Monitors tab creation, lifecycle events, and tracks agent focus."""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		BrowserStoppedEvent,
		TabCreatedEvent,
		TabClosedEvent,
		SwitchTabEvent,
		NavigateToUrlEvent,
		NavigationCompleteEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent]]] = [
		AgentFocusChangedEvent,
		BrowserErrorEvent,
		TabClosedEvent,
		NavigationStartedEvent,
		NavigationCompleteEvent,
	]

	# Agent focus tracking - using regular fields so they can be accessed as properties
	page: Page | None = Field(default=None, exclude=True)

	async def attach_to_page(self, page: Page) -> None:
		"""Set up monitoring for a page - tracks page lifecycle."""
		logger.debug(f'[NavigationWatchdog] Started tracking page: {page.url}')
		page.on('close', lambda p: self._handle_page_close(page))

	# ========== Browser Lifecycle Events ==========

	async def on_BrowserStoppedEvent(self, event: BrowserStoppedEvent) -> None:
		"""Clear agent focus when browser stops."""
		logger.info('[NavigationWatchdog] Browser stopped')
		self.page = None

	# ========== Tab Lifecycle Events ==========

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Handle new tab creation - track page and possibly move agent focus."""
		logger.debug(f'[NavigationWatchdog] Tab created: {event.url}')

		# Get the page from browser context and track it
		try:
			page = self.browser_session.get_page_by_tab_index(event.tab_index)
			if page:
				self._track_page(page)
		except Exception as e:
			logger.error(f'[NavigationWatchdog] Error tracking new page: {e}')

		# When a new tab is created, agent typically focuses on it immediately
		await self._update_agent_focus_to_latest_tab()

	async def on_TabClosedEvent(self, event: TabClosedEvent) -> None:
		"""Handle tab closure."""
		logger.debug(f'[NavigationWatchdog] Tab closed at index {event.tab_index}')

		# If the closed tab was the agent's current page, find a new one
		if self.tab_index == event.tab_index:
			await self._find_new_agent_page()
		# No need to adjust tab_index since it's computed from page position

	async def on_SwitchTabEvent(self, event: SwitchTabEvent) -> None:
		"""Handle explicit tab switches by the agent."""
		logger.debug(f'[NavigationWatchdog] Agent switching to tab {event.tab_index}')
		await self._switch_agent_focus_to_tab(event.tab_index)

	async def on_NavigateToUrlEvent(self, event: NavigateToUrlEvent) -> None:
		"""Handle all navigation requests with security enforcement and complete logic."""
		# SECURITY CHECK: Block disallowed URLs before navigation starts
		if not self._is_url_allowed(event.url):
			logger.warning(f'⛔️ Blocking navigation to disallowed URL: {event.url}')
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='NavigationBlocked',
					message=f'Navigation blocked to disallowed URL: {event.url}',
					details={'url': event.url, 'reason': 'not_in_allowed_domains'},
				)
			)
			return

		try:
			# Handle new tab navigation
			if event.new_tab:
				if not self.browser_session._browser_context:
					return

				# Create new page
				page = await self.browser_session._browser_context.new_page()

				# Get tab index for events (after adding the page)
				tab_index = len(self.browser_session.tabs) - 1

				# Navigate to URL if provided
				if event.url:
					# Dispatch navigation started event
					from browser_use.browser.events import NavigationStartedEvent

					self.event_bus.dispatch(
						NavigationStartedEvent(
							tab_index=tab_index,
							url=event.url,
						)
					)

					try:
						# Perform navigation with timeout protection
						response = await asyncio.wait_for(
							page.goto(event.url, wait_until=event.wait_until),
							timeout=30.0,  # 30 second timeout to prevent hanging
						)

						# Dispatch completion event
						self.event_bus.dispatch(
							NavigationCompleteEvent(
								tab_index=tab_index,
								url=event.url,
								status=response.status if response else None,
							)
						)

						# Network monitoring is handled by CrashWatchdog

					except TimeoutError:
						# Handle navigation timeout for new tab
						error_message = 'Navigation timed out after 30 seconds'
						loading_status = 'Navigation timeout: 30 seconds'
						logger.warning(f'[NavigationWatchdog] Navigation to {event.url} timed out in new tab')

						self.event_bus.dispatch(
							NavigationCompleteEvent(
								tab_index=tab_index,
								url=event.url,
								status=None,
								error_message=error_message,
								loading_status=loading_status,
							)
						)
					except Exception as e:
						# Handle other navigation errors for new tab
						error_message = str(e)
						loading_status = None
						if 'timeout' in error_message.lower() or 'timed out' in error_message.lower():
							loading_status = f'Navigation timeout: {error_message}'

						self.event_bus.dispatch(
							NavigationCompleteEvent(
								tab_index=tab_index,
								url=event.url,
								status=None,
								error_message=error_message,
								loading_status=loading_status,
							)
						)

				# Update agent focus to the new tab immediately
				self.page = page
				self._dispatch_focus_changed()

				# ONLY dispatch TabCreatedEvent for NEW tabs (not existing tab navigation)
				from browser_use.browser.events import TabCreatedEvent

				self.event_bus.dispatch(
					TabCreatedEvent(
						tab_index=tab_index,
						url=page.url,  # Use actual page URL
					)
				)
				return

			# Handle timeout navigation
			if event.timeout_ms is not None:
				# Create a new navigation event without timeout for the actual navigation
				nav_event = self.event_bus.dispatch(NavigateToUrlEvent(url=event.url, wait_until=event.wait_until))
				try:
					await asyncio.wait_for(nav_event, timeout=event.timeout_ms / 1000.0)
				except TimeoutError:
					logger.warning(f'Navigation to {event.url} timed out after {event.timeout_ms}ms')
					# Dispatch NavigationCompleteEvent for timeout error
					self.event_bus.dispatch(
						NavigationCompleteEvent(
							tab_index=0,  # Default tab index since we don't have access to the actual page
							url=event.url,
							status=None,
							error_message=f'Navigation timed out after {event.timeout_ms}ms',
							loading_status=f'Navigation timeout after {event.timeout_ms}ms',
						)
					)
				return

			# Handle standard navigation
			# Get the page to navigate - use current agent page or create one
			page = None
			try:
				page = await self.get_or_create_page()
			except Exception:
				# Fallback to first page
				if self.browser_session.pages:
					page = self.browser_session.pages[0]

			if not page:
				raise ValueError('Failed to get or create a page for navigation')

			# Get tab index
			tab_index = self.browser_session.get_tab_index(page)

			# Dispatch navigation started event
			from browser_use.browser.events import NavigationStartedEvent

			self.event_bus.dispatch(
				NavigationStartedEvent(
					tab_index=tab_index,
					url=event.url,
				)
			)

			# Perform navigation with timeout protection
			response = await asyncio.wait_for(
				page.goto(
					event.url,
					wait_until=event.wait_until,
				),
				timeout=30.0,  # 30 second timeout to prevent hanging
			)

			# Dispatch completion event
			self.event_bus.dispatch(
				NavigationCompleteEvent(
					tab_index=tab_index,
					url=event.url,
					status=response.status if response else None,
				)
			)

			# Network monitoring is handled by CrashWatchdog

		except TimeoutError:
			# Handle navigation timeout for standard navigation
			error_message = 'Navigation timed out after 30 seconds'
			loading_status = 'Navigation timeout: 30 seconds'
			logger.warning(f'[NavigationWatchdog] Navigation to {event.url} timed out in standard navigation')

			# Get tab index for timeout error reporting
			tab_index = self.browser_session.get_tab_index(page) if page else 0

			# Dispatch NavigationCompleteEvent with timeout error details
			self.event_bus.dispatch(
				NavigationCompleteEvent(
					tab_index=tab_index,
					url=event.url,
					status=None,
					error_message=error_message,
					loading_status=loading_status,
				)
			)
		except Exception as e:
			# Handle other navigation errors
			error_message = str(e)
			loading_status = None

			# Check for timeout errors
			if 'timeout' in error_message.lower() or 'timed out' in error_message.lower():
				loading_status = f'Navigation timeout: {error_message}'

			# Get tab index for error reporting
			tab_index = 0  # Default to first tab for errors

			# Dispatch NavigationCompleteEvent with error details
			self.event_bus.dispatch(
				NavigationCompleteEvent(
					tab_index=tab_index,
					url=event.url,
					status=None,
					error_message=error_message,
					loading_status=loading_status,
				)
			)

	async def on_NavigationCompleteEvent(self, event: NavigationCompleteEvent) -> None:
		"""Update agent focus when navigation completes and enforce security."""
		# Check if the navigated URL is allowed
		if not self._is_url_allowed(event.url):
			logger.warning(f'⛔️ Navigation to non-allowed URL detected: {event.url}')
			# Dispatch browser error
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='NavigationBlocked',
					message=f'Navigation to non-allowed URL: {event.url}',
					details={'url': event.url, 'tab_index': event.tab_index},
				)
			)
			# Close the page that navigated to the disallowed URL
			try:
				if self.browser_session._browser_context:
					pages = self.browser_session._browser_context.pages
					if 0 <= event.tab_index < len(pages):
						page = pages[event.tab_index]
						await page.close()
						logger.info(f'⛔️ Closed page with non-allowed URL: {event.url}')
			except Exception as e:
				logger.error(f'⛔️ Failed to close page with non-allowed URL: {str(e)}')
			return

		# Agent focus stays on the tab that navigated
		if event.tab_index != self.tab_index:
			await self._switch_agent_focus_to_tab(event.tab_index)

	# ========== Tab Tracking Methods ==========

	def _track_page(self, page: Page) -> None:
		"""Track a page for lifecycle events."""
		logger.debug(f'[NavigationWatchdog] Started tracking page: {page.url}')

		# Set up page close handler
		page.on('close', lambda p: self._handle_page_close(page))

	def _handle_page_close(self, page: Page) -> None:
		"""Handle page close event."""
		try:
			# Try to get tab index before page is fully closed
			tab_index = self.browser_session.get_tab_index(page)
			if tab_index == -1:
				tab_index = 0  # Fallback if page already removed

			# Emit TabClosedEvent
			self.event_bus.dispatch(TabClosedEvent(tab_index=tab_index))
			logger.info(f'[NavigationWatchdog] Page closed, emitted TabClosedEvent for tab {tab_index}')

		except Exception as e:
			logger.error(f'[NavigationWatchdog] Error handling page close: {e}')

	# ========== Security Methods ==========

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

		# Always allow internal browser pages
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
				import fnmatch

				# Check if pattern matches the host
				if pattern.startswith('*.'):
					# Pattern like *.example.com should match subdomains and main domain
					# But only for http/https URLs unless scheme is specified
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

	# ========== Agent Focus Tracking Methods ==========

	@property
	def current_agent_page(self) -> Page | None:
		"""Get the current page the agent is focused on."""
		return self.page

	@property
	def current_agent_tab_index(self) -> int:
		"""Get the current tab index the agent is focused on."""
		return self.tab_index

	@property
	def tab_index(self) -> int:
		"""Get the current tab index derived from page position in browser_session.pages."""
		if self.page is None:
			return 0
		return self.browser_session.get_tab_index(self.page)

	async def _initialize_agent_focus(self) -> None:
		"""Initialize agent focus to first available page."""
		if not self.browser_session._browser_context:
			return

		pages = self.browser_session._browser_context.pages
		if pages:
			self.page = pages[0]
			self._dispatch_focus_changed()
			try:
				current_page = await self.browser_session.get_current_page()
				logger.info(f'[NavigationWatchdog] Initial agent focus set to tab 0: {current_page.url}')
			except ValueError:
				logger.info('[NavigationWatchdog] Initial agent focus set to tab 0')

	async def _update_agent_focus_to_latest_tab(self) -> None:
		"""Update agent focus to the latest (most recently created) tab."""
		if self.browser_session.pages:
			# Focus on the last tab (most recently created)
			self.page = self.browser_session.pages[-1]
			self._dispatch_focus_changed()
			try:
				current_page = await self.browser_session.get_current_page()
				logger.info(f'[NavigationWatchdog] Agent focus moved to new tab {self.tab_index}: {current_page.url}')
			except ValueError:
				logger.info(f'[NavigationWatchdog] Agent focus moved to new tab {self.tab_index}')

	async def _switch_agent_focus_to_tab(self, tab_index: int) -> None:
		"""Switch agent focus to a specific tab index."""
		page = self.browser_session.get_page_by_tab_index(tab_index)
		if page:
			self.page = page
			self._dispatch_focus_changed()
			try:
				current_page = await self.browser_session.get_current_page()
				logger.info(f'[NavigationWatchdog] Agent focus switched to tab {tab_index}: {current_page.url}')
			except ValueError:
				logger.info(f'[NavigationWatchdog] Agent focus switched to tab {tab_index}')

	async def _find_new_agent_page(self) -> None:
		"""Find a new page for agent focus when current one is closed."""
		if self.browser_session.pages:
			# Try to stay at the same index, or go to the previous one
			new_index = min(self.tab_index, len(self.browser_session.pages) - 1)
			self.page = self.browser_session.pages[new_index]
			self._dispatch_focus_changed()
			try:
				current_page = await self.browser_session.get_current_page()
				logger.info(f'[NavigationWatchdog] Agent focus moved to tab {new_index}: {current_page.url}')
			except ValueError:
				logger.info(f'[NavigationWatchdog] Agent focus moved to tab {new_index}')
		else:
			self.page = None

	def _dispatch_focus_changed(self) -> None:
		"""Dispatch event when agent focus changes."""
		if self.page:
			try:
				self.event_bus.dispatch(
					AgentFocusChangedEvent(
						tab_index=self.tab_index,
						url=self.page.url,
					)
				)
			except Exception as e:
				logger.error(f'[NavigationWatchdog] Error dispatching focus change: {e}')

	async def get_or_create_page(self) -> Page:
		"""Get current agent page or create a new one if none exists."""
		if self.page and not self.page.is_closed():
			# Check if current page URL is still allowed
			if not self._is_url_allowed(self.page.url):
				logger.warning(f'⛔️ Current page URL no longer allowed: {self.page.url}')
				# Close the current page and find/create a new one
				try:
					await self.page.close()
				except Exception:
					pass
				self.page = None
			else:
				return self.page

		# No current page, request tabs info to find one
		self.event_bus.dispatch(TabsInfoRequestEvent())
		try:
			event_result = await self.event_bus.expect(TabsInfoResponseEvent, timeout=5.0)
			response: TabsInfoResponseEvent = event_result  # type: ignore
			if response.tabs:
				# Find the first tab with an allowed URL
				for i, tab in enumerate(response.tabs):
					if self._is_url_allowed(tab.get('url', 'about:blank')):
						await self._switch_agent_focus_to_tab(i)
						if self.page:
							return self.page
		except TimeoutError:
			pass

		# No tabs available or no allowed tabs, create a new one with about:blank
		logger.info('[NavigationWatchdog] No active page, creating new tab')
		nav_event = self.event_bus.dispatch(NavigateToUrlEvent(url='about:blank', new_tab=True))
		await nav_event  # Wait for navigation to complete

		# Try to get the new page
		if self.browser_session.pages:
			self.page = self.browser_session.pages[-1]
			self._dispatch_focus_changed()
			if self.page:
				return self.page

		raise ValueError('Failed to create or find an active page')
