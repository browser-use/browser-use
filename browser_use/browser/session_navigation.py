"""BrowserSession navigation event handling."""

from __future__ import annotations

import asyncio
from typing import Any

from browser_use.browser.events import (
	AgentFocusChangedEvent,
	NavigateToUrlEvent,
	NavigationCompleteEvent,
	NavigationStartedEvent,
	TabCreatedEvent,
)
from browser_use.utils import is_new_tab_page


class BrowserSessionNavigationMixin:
	"""Navigation event handlers for BrowserSession."""

	async def on_NavigateToUrlEvent(self: Any, event: NavigateToUrlEvent) -> None:
		"""Handle navigation requests - core browser functionality."""
		await self.navigate_to_url_direct(
			event.url,
			new_tab=event.new_tab,
			timeout_ms=event.timeout_ms,
			wait_until=event.wait_until,
			event_timeout=event.event_timeout,
		)

	async def navigate_to_url_direct(
		self: Any,
		url: str,
		*,
		new_tab: bool = False,
		timeout_ms: int | None = None,
		wait_until: str = 'load',
		event_timeout: float | None = None,
	) -> None:
		"""Navigate to a URL without routing through a navigation request event."""

		self.logger.debug(f'[navigate_to_url_direct] url={url}, new_tab={new_tab}')
		if not self.agent_focus_target_id:
			self.logger.warning('Cannot navigate - browser not connected')
			return

		target_id = None
		current_target_id = self.agent_focus_target_id

		current_target = self.session_manager.get_target(current_target_id)
		if new_tab and is_new_tab_page(current_target.url):
			self.logger.debug(f'[on_NavigateToUrlEvent] Already on blank tab ({current_target.url}), reusing')
			new_tab = False

		try:
			self.logger.debug(f'[on_NavigateToUrlEvent] Processing new_tab={new_tab}')

			if new_tab:
				page_targets = self.session_manager.get_all_page_targets()
				self.logger.debug(f'[on_NavigateToUrlEvent] Found {len(page_targets)} existing tabs')

				for idx, target in enumerate(page_targets):
					self.logger.debug(f'[on_NavigateToUrlEvent] Tab {idx}: url={target.url}, targetId={target.target_id}')
					if target.url == 'about:blank' and target.target_id != current_target_id:
						target_id = target.target_id
						self.logger.debug(f'Reusing existing about:blank tab #{target_id[-4:]}')
						break

				if not target_id:
					self.logger.debug('[on_NavigateToUrlEvent] No reusable about:blank tab found, creating new tab...')
					try:
						target_id = await self._cdp_create_new_page('about:blank')
						self.logger.debug(f'Created new tab #{target_id[-4:]}')
						await self.event_bus.dispatch(TabCreatedEvent(target_id=target_id, url='about:blank'))
					except Exception as e:
						self.logger.error(f'[on_NavigateToUrlEvent] Failed to create new tab: {type(e).__name__}: {e}')
						target_id = current_target_id
						self.logger.warning(f'[on_NavigateToUrlEvent] Falling back to current tab #{target_id[-4:]}')
			else:
				target_id = target_id or current_target_id

			if self.agent_focus_target_id is None or self.agent_focus_target_id != target_id:
				self.logger.debug(
					f'[on_NavigateToUrlEvent] Switching to target tab {target_id[-4:]} (current: {self.agent_focus_target_id[-4:] if self.agent_focus_target_id else "none"})'
				)
				await self.switch_tab_direct(target_id)
			else:
				self.logger.debug(f'[on_NavigateToUrlEvent] Already on target tab {target_id[-4:]}, skipping SwitchTabEvent')

			assert self.agent_focus_target_id is not None and self.agent_focus_target_id == target_id, (
				'Agent focus not updated to new target_id after SwitchTabEvent should have switched to it'
			)

			await self.event_bus.dispatch(NavigationStartedEvent(target_id=target_id, url=url))

			await self._navigate_and_wait(
				url,
				target_id,
				timeout=timeout_ms / 1000 if timeout_ms is not None else None,
				wait_until=wait_until,
				nav_timeout=event_timeout,
			)

			await self._close_extension_options_pages()

			self.logger.debug(f'Dispatching NavigationCompleteEvent for {url} (tab #{target_id[-4:]})')
			await self.event_bus.dispatch(
				NavigationCompleteEvent(
					target_id=target_id,
					url=url,
					status=None,
				)
			)
			await self.event_bus.dispatch(AgentFocusChangedEvent(target_id=target_id, url=url))

		except Exception as e:
			self.logger.error(f'Navigation failed: {type(e).__name__}: {e}')
			if target_id:
				await self.event_bus.dispatch(
					NavigationCompleteEvent(
						target_id=target_id,
						url=url,
						error_message=f'{type(e).__name__}: {e}',
					)
				)
				await self.event_bus.dispatch(AgentFocusChangedEvent(target_id=target_id, url=url))
			raise

	async def _navigate_and_wait(
		self: Any,
		url: str,
		target_id: str,
		timeout: float | None = None,
		wait_until: str = 'load',
		nav_timeout: float | None = None,
	) -> None:
		"""Navigate to URL and wait for page readiness using CDP lifecycle events."""
		cdp_session = await self.get_or_create_cdp_session(target_id, focus=False)

		if timeout is None:
			target = self.session_manager.get_target(target_id)
			current_url = target.url
			same_domain = (
				url.split('/')[2] == current_url.split('/')[2]
				if url.startswith('http') and current_url.startswith('http')
				else False
			)
			timeout = 3.0 if same_domain else 8.0

		nav_start_time = asyncio.get_event_loop().time()

		if nav_timeout is None:
			nav_timeout = 20.0
		try:
			nav_result = await asyncio.wait_for(
				cdp_session.cdp_client.send.Page.navigate(
					params={'url': url, 'transitionType': 'address_bar'},
					session_id=cdp_session.session_id,
				),
				timeout=nav_timeout,
			)
		except TimeoutError:
			duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
			raise RuntimeError(f'Page.navigate() timed out after {nav_timeout}s ({duration_ms:.0f}ms) for {url}')

		if nav_result.get('errorText'):
			raise RuntimeError(f'Navigation failed: {nav_result["errorText"]}')

		if wait_until == 'commit':
			duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
			self.logger.debug(f'✅ Page ready for {url} (commit, {duration_ms:.0f}ms)')
			return

		navigation_id = nav_result.get('loaderId')
		start_time = asyncio.get_event_loop().time()
		seen_events = []

		if not hasattr(cdp_session, '_lifecycle_events'):
			raise RuntimeError(
				f'❌ Lifecycle monitoring not enabled for {cdp_session.target_id[:8]}! '
				f'This is a bug - SessionManager should have initialized it. '
				f'Session: {cdp_session}'
			)

		acceptable_events: set[str] = {'networkIdle'}
		if wait_until in ('load', 'domcontentloaded'):
			acceptable_events.add('load')
		if wait_until == 'domcontentloaded':
			acceptable_events.add('DOMContentLoaded')

		poll_interval = 0.05
		while (asyncio.get_event_loop().time() - start_time) < timeout:
			try:
				for event_data in list(cdp_session._lifecycle_events):
					event_name = event_data.get('name')
					event_loader_id = event_data.get('loaderId')

					event_str = f'{event_name}(loader={event_loader_id[:8] if event_loader_id else "none"})'
					if event_str not in seen_events:
						seen_events.append(event_str)

					if event_loader_id and navigation_id and event_loader_id != navigation_id:
						continue

					if event_name in acceptable_events:
						duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
						self.logger.debug(f'✅ Page ready for {url} ({event_name}, {duration_ms:.0f}ms)')
						return

			except Exception as e:
				self.logger.debug(f'Error polling lifecycle events: {e}')

			await asyncio.sleep(poll_interval)

		duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
		if not seen_events:
			self.logger.error(
				f'❌ No lifecycle events received for {url} after {duration_ms:.0f}ms! '
				f'Monitoring may have failed. Target: {cdp_session.target_id[:8]}'
			)
		else:
			self.logger.warning(f'⚠️ Page readiness timeout ({timeout}s, {duration_ms:.0f}ms) for {url}')
