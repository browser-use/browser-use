"""About:blank watchdog for managing about:blank tabs with DVD screensaver."""

from typing import TYPE_CHECKING, ClassVar

from bubus import BaseEvent
from pydantic import PrivateAttr

from browser_use.browser.events import (
	AboutBlankDVDScreensaverShownEvent,
	BrowserStopEvent,
	BrowserStoppedEvent,
	CloseTabEvent,
	NavigateToUrlEvent,
	TabClosedEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog

if TYPE_CHECKING:
	pass


class AboutBlankWatchdog(BaseWatchdog):
	"""Ensures there's always exactly one about:blank tab with DVD screensaver."""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		BrowserStopEvent,
		BrowserStoppedEvent,
		TabCreatedEvent,
		TabClosedEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent]]] = [
		NavigateToUrlEvent,
		CloseTabEvent,
		AboutBlankDVDScreensaverShownEvent,
	]

	_stopping: bool = PrivateAttr(default=False)

	async def on_BrowserStopEvent(self, event: BrowserStopEvent) -> None:
		"""Handle browser stop request - stop creating new tabs."""
		# logger.info('[AboutBlankWatchdog] Browser stop requested, stopping tab creation')
		self._stopping = True

	async def on_BrowserStoppedEvent(self, event: BrowserStoppedEvent) -> None:
		"""Handle browser stopped event."""
		# logger.info('[AboutBlankWatchdog] Browser stopped')
		self._stopping = True

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Check tabs when a new tab is created."""
		# logger.debug(f'[AboutBlankWatchdog] ➕ New tab created: {event.url}')

		# If an about:blank tab was created, show DVD screensaver on all about:blank tabs
		if event.url == 'about:blank':
			await self._show_dvd_screensaver_on_about_blank_tabs()

	async def on_TabClosedEvent(self, event: TabClosedEvent) -> None:
		"""Check tabs when a tab is closed and proactively create about:blank if needed."""
		# logger.debug('[AboutBlankWatchdog] Tab closing, checking if we need to create about:blank tab')

		# Don't create new tabs if browser is shutting down
		if self._stopping:
			# logger.debug('[AboutBlankWatchdog] Browser is stopping, not creating new tabs')
			return

		# Check if we're about to close the last tab (event happens BEFORE tab closes)
		# Use _cdp_get_all_pages for quick check without fetching titles
		page_targets = await self.browser_session._cdp_get_all_pages()
		if len(page_targets) <= 1:
			self.logger.info(
				'[AboutBlankWatchdog] Last tab closing, creating new about:blank tab to avoid closing entire browser'
			)
			# Create the animation tab since no tabs should remain
			navigate_event = self.event_bus.dispatch(NavigateToUrlEvent(url='about:blank', new_tab=True))
			await navigate_event
			# Show DVD screensaver on the new tab
			await self._show_dvd_screensaver_on_about_blank_tabs()
		else:
			# Multiple tabs exist, check after close
			await self._check_and_ensure_about_blank_tab()

	async def attach_to_target(self, target_id: str) -> None:
		"""AboutBlankWatchdog doesn't monitor individual targets."""
		pass

	async def _check_and_ensure_about_blank_tab(self) -> None:
		"""Check current tabs and ensure exactly one about:blank tab with animation exists."""
		try:
			# For quick checks, just get page targets without titles to reduce noise
			page_targets = await self.browser_session._cdp_get_all_pages()

			# If no tabs exist at all, create one to keep browser alive
			if len(page_targets) == 0:
				# Only create a new tab if there are no tabs at all
				self.logger.info('[AboutBlankWatchdog] No tabs exist, creating new about:blank DVD screensaver tab')
				navigate_event = self.event_bus.dispatch(NavigateToUrlEvent(url='about:blank', new_tab=True))
				await navigate_event
				# Show DVD screensaver on the new tab
				await self._show_dvd_screensaver_on_about_blank_tabs()
			# Otherwise there are tabs, don't create new ones to avoid interfering

		except Exception as e:
			self.logger.error(f'[AboutBlankWatchdog] Error ensuring about:blank tab: {e}')

	async def _show_dvd_screensaver_on_about_blank_tabs(self) -> None:
		"""Show DVD screensaver on all about:blank pages only."""
		try:
			# Get just the page targets without expensive title fetching
			page_targets = await self.browser_session._cdp_get_all_pages()
			browser_session_label = str(self.browser_session.id)[-4:]

			for page_target in page_targets:
				target_id = page_target['targetId']
				url = page_target['url']

				# Only target about:blank pages specifically
				if url == 'about:blank':
					await self._show_dvd_screensaver_loading_animation_cdp(target_id, browser_session_label)

		except Exception as e:
			self.logger.error(f'[AboutBlankWatchdog] Error showing DVD screensaver: {e}')

	async def _show_dvd_screensaver_loading_animation_cdp(self, target_id: str, browser_session_label: str) -> None:
		"""
		Injects a DVD screensaver-style bouncing logo loading animation overlay into the target using CDP.
		This is used to visually indicate that the browser is setting up or waiting.
		"""
		try:
			# Create temporary session for this target without switching focus
			temp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			# Inject the DVD screensaver script (from main branch with idempotency added)
			script = f"""
				(function(browser_session_label) {{
					// Idempotency check
					if (window.__dvdAnimationRunning) {{
						return; // Already running, don't add another
					}}
					window.__dvdAnimationRunning = true;
					
					// Ensure document.body exists before proceeding
					if (!document.body) {{
						// Try again after DOM is ready
						window.__dvdAnimationRunning = false; // Reset flag to retry
						if (document.readyState === 'loading') {{
							document.addEventListener('DOMContentLoaded', () => arguments.callee(browser_session_label));
						}}
						return;
					}}
					
					const animated_title = `Starting agent ${{browser_session_label}}...`;
					if (document.title === animated_title) {{
						return;      // already run on this tab, dont run again
					}}
					document.title = animated_title;

					// Create the main overlay
					const loadingOverlay = document.createElement('div');
					loadingOverlay.id = 'pretty-loading-animation';
					loadingOverlay.style.position = 'fixed';
					loadingOverlay.style.top = '0';
					loadingOverlay.style.left = '0';
					loadingOverlay.style.width = '100vw';
					loadingOverlay.style.height = '100vh';
					loadingOverlay.style.background = '#000';
					loadingOverlay.style.zIndex = '99999';
					loadingOverlay.style.overflow = 'hidden';

					// Create the image element
					const img = document.createElement('img');
					img.src = 'https://cf.browser-use.com/logo.svg';
					img.alt = 'Browser-Use';
					img.style.width = '200px';
					img.style.height = 'auto';
					img.style.position = 'absolute';
					img.style.left = '0px';
					img.style.top = '0px';
					img.style.zIndex = '2';
					img.style.opacity = '0.8';

					loadingOverlay.appendChild(img);
					document.body.appendChild(loadingOverlay);

					// DVD screensaver bounce logic
					let x = Math.random() * (window.innerWidth - 300);
					let y = Math.random() * (window.innerHeight - 300);
					let dx = 1.2 + Math.random() * 0.4; // px per frame
					let dy = 1.2 + Math.random() * 0.4;
					// Randomize direction
					if (Math.random() > 0.5) dx = -dx;
					if (Math.random() > 0.5) dy = -dy;

					function animate() {{
						const imgWidth = img.offsetWidth || 300;
						const imgHeight = img.offsetHeight || 300;
						x += dx;
						y += dy;

						if (x <= 0) {{
							x = 0;
							dx = Math.abs(dx);
						}} else if (x + imgWidth >= window.innerWidth) {{
							x = window.innerWidth - imgWidth;
							dx = -Math.abs(dx);
						}}
						if (y <= 0) {{
							y = 0;
							dy = Math.abs(dy);
						}} else if (y + imgHeight >= window.innerHeight) {{
							y = window.innerHeight - imgHeight;
							dy = -Math.abs(dy);
						}}

						img.style.left = `${{x}}px`;
						img.style.top = `${{y}}px`;

						requestAnimationFrame(animate);
					}}
					animate();

					// Responsive: update bounds on resize
					window.addEventListener('resize', () => {{
						x = Math.min(x, window.innerWidth - img.offsetWidth);
						y = Math.min(y, window.innerHeight - img.offsetHeight);
					}});

					// Add a little CSS for smoothness
					const style = document.createElement('style');
					style.textContent = `
						#pretty-loading-animation {{
							/*backdrop-filter: blur(2px) brightness(0.9);*/
						}}
						#pretty-loading-animation img {{
							user-select: none;
							pointer-events: none;
						}}
					`;
					document.head.appendChild(style);
				}})('{browser_session_label}');
			"""

			await temp_session.cdp_client.send.Runtime.evaluate(params={'expression': script}, session_id=temp_session.session_id)

			# No need to detach - session is cached

			# Dispatch event
			tab_index = await self.browser_session.get_tab_index(target_id)
			self.event_bus.dispatch(AboutBlankDVDScreensaverShownEvent(tab_index=tab_index))

		except Exception as e:
			self.logger.error(f'[AboutBlankWatchdog] Error injecting DVD screensaver: {e}')
