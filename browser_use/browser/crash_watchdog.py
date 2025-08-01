"""Browser watchdog for monitoring crashes and network timeouts."""

import asyncio
import time
from typing import TYPE_CHECKING, Any, ClassVar

from bubus import BaseEvent
from playwright.async_api import Page, Request, Response
from pydantic import Field, PrivateAttr

from browser_use.browser.events import (
	BrowserErrorEvent,
	BrowserStartedEvent,
	BrowserStoppedEvent,
	PageCrashedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.utils import logger

if TYPE_CHECKING:
	pass


class NetworkRequestTracker:
	"""Tracks ongoing network requests."""

	def __init__(self, request: Request, start_time: float, url: str, method: str, resource_type: str | None = None):
		self.request = request
		self.start_time = start_time
		self.url = url
		self.method = method
		self.resource_type = resource_type


class CrashWatchdog(BaseWatchdog):
	"""Monitors browser health for crashes and network timeouts."""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		BrowserStartedEvent,
		BrowserStoppedEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent]]] = [
		BrowserErrorEvent,
		PageCrashedEvent,
	]

	# Configuration
	network_timeout_seconds: float = Field(default=10.0)
	check_interval_seconds: float = Field(default=1.0)

	# Private state
	_browser_pid: int | None = PrivateAttr(default=None)
	_active_requests: dict[str, NetworkRequestTracker] = PrivateAttr(default_factory=dict)
	_monitoring_task: asyncio.Task | None = PrivateAttr(default=None)
	_cdp_session: Any = PrivateAttr(default=None)
	_last_responsive_checks: dict[str, float] = PrivateAttr(default_factory=dict)  # page_url -> timestamp

	async def on_BrowserStartedEvent(self, event: BrowserStartedEvent) -> None:
		"""Start monitoring when browser starts."""
		logger.info('[CrashWatchdog] Browser started event received, beginning monitoring')

		# Get browser pid from event or session
		self._browser_pid = event.browser_pid or self.browser_session.browser_pid

		await self._start_monitoring()
		logger.info(f'[CrashWatchdog] Monitoring task started: {self._monitoring_task and not self._monitoring_task.done()}')

	async def on_BrowserStoppedEvent(self, event: BrowserStoppedEvent) -> None:
		"""Stop monitoring when browser stops."""
		logger.info('[Watchdog] Browser stopped, ending monitoring')
		await self._stop_monitoring()

	async def attach_to_page(self, page: Page) -> None:
		"""Set up crash monitoring for a specific page."""
		# Network request tracking
		page.on('request', lambda req: asyncio.create_task(self._on_request(req)))
		page.on('response', lambda resp: self._on_response(resp))
		page.on('requestfailed', lambda req: self._on_request_failed(req))

		def _on_request_finished(req: Request) -> None:
			self._active_requests.pop(f'{id(req)}', None)

		page.on('requestfinished', _on_request_finished)

		# Page crash detection
		page.on('crash', lambda _: asyncio.create_task(self._on_page_crash(page)))

		logger.debug(f'[CrashWatchdog] Added page to monitoring: {page.url}')

	async def _on_request(self, request: Request) -> None:
		"""Track new network request."""
		request_id = f'{id(request)}'
		self._active_requests[request_id] = NetworkRequestTracker(
			request=request,
			start_time=time.time(),
			url=request.url,
			method=request.method,
			resource_type=request.resource_type,
		)
		logger.debug(f'[Watchdog] Tracking request: {request.method} {request.url[:50]}...')

	def _on_response(self, response: Response) -> None:
		"""Remove request from tracking on response."""
		request_id = f'{id(response.request)}'
		if request_id in self._active_requests:
			elapsed = time.time() - self._active_requests[request_id].start_time
			logger.debug(f'[Watchdog] Request completed in {elapsed:.2f}s: {response.url[:50]}...')
			del self._active_requests[request_id]

	def _on_request_failed(self, request: Request) -> None:
		"""Remove request from tracking on failure."""
		request_id = f'{id(request)}'
		if request_id in self._active_requests:
			elapsed = time.time() - self._active_requests[request_id].start_time
			logger.debug(f'[Watchdog] Request failed after {elapsed:.2f}s: {request.url[:50]}...')
			del self._active_requests[request_id]

	async def _on_page_crash(self, page: Page) -> None:
		"""Handle page crash."""
		logger.error(f'[Watchdog] Page crashed: {page.url}')

		tab_index = self.browser_session.get_tab_index(page)

		# Emit crash event
		self.event_bus.dispatch(
			PageCrashedEvent(
				tab_index=tab_index,
				error='Page crashed unexpectedly',
			)
		)

		# Also emit generic browser error
		self.event_bus.dispatch(
			BrowserErrorEvent(
				error_type='PageCrash',
				message=f'Page crashed: {page.url}',
				details={
					'url': page.url,
					'tab_index': tab_index,
				},
			)
		)

	async def _start_monitoring(self) -> None:
		"""Start the monitoring loop."""
		if self._monitoring_task and not self._monitoring_task.done():
			logger.info('[CrashWatchdog] Monitoring already running')
			return

		self._monitoring_task = asyncio.create_task(self._monitoring_loop())
		logger.info('[CrashWatchdog] Monitoring loop created and started')

		# Set up CDP session for browser crash detection
		if self.browser_session._browser:
			try:
				# Get CDP session from browser
				browser = self.browser_session._browser
				context = self.browser_session._browser_context
				if context and context.pages:
					cdp_contexts = await context.new_cdp_session(context.pages[0])
					self._cdp_session = cdp_contexts

				# Enable crash detection domains
				if self._cdp_session:
					await self._cdp_session.send('Inspector.enable')
					await self._cdp_session.send('Page.enable')

				# Set up crash handlers
				if self._cdp_session:
					self._cdp_session.on(
						'Inspector.targetCrashed',
						lambda params: (
							logger.error('[Watchdog] Browser crash detected via CDP'),
							self.event_bus.dispatch(
								BrowserErrorEvent(error_type='BrowserCrash', message='Browser process crashed', details=params)
							),
						),
					)

				logger.info('[Watchdog] CDP crash detection enabled')
			except Exception as e:
				logger.warning(f'[Watchdog] Failed to set up CDP crash detection: {e}')

	async def _stop_monitoring(self) -> None:
		"""Stop the monitoring loop."""
		if self._monitoring_task and not self._monitoring_task.done():
			self._monitoring_task.cancel()
			try:
				await self._monitoring_task
			except asyncio.CancelledError:
				pass
			logger.info('[Watchdog] Monitoring loop stopped')

		# Clean up CDP session
		if self._cdp_session:
			try:
				await self._cdp_session.detach()
			except Exception:
				pass
			self._cdp_session = None

		# Clear tracking
		self._active_requests.clear()
		# No _pages attribute in this watchdog

	async def _monitoring_loop(self) -> None:
		"""Main monitoring loop."""
		while True:
			try:
				await self._check_network_timeouts()
				await self._check_browser_health()
				await asyncio.sleep(self.check_interval_seconds)
			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.error(f'[Watchdog] Error in monitoring loop: {e}')

	async def _check_network_timeouts(self) -> None:
		"""Check for network requests exceeding timeout."""
		current_time = time.time()
		timed_out_requests = []

		# Debug logging
		if self._active_requests:
			logger.debug(
				f'[Watchdog] Checking {len(self._active_requests)} active requests for timeouts (threshold: {self.network_timeout_seconds}s)'
			)

		for request_id, tracker in self._active_requests.items():
			elapsed = current_time - tracker.start_time
			logger.debug(
				f'[Watchdog] Request {tracker.url[:30]}... elapsed: {elapsed:.1f}s, timeout: {self.network_timeout_seconds}s'
			)
			if elapsed >= self.network_timeout_seconds:
				timed_out_requests.append((request_id, tracker))

		# Emit events for timed out requests
		for request_id, tracker in timed_out_requests:
			logger.warning(
				f'[Watchdog] Network request timeout after {self.network_timeout_seconds}s: '
				f'{tracker.method} {tracker.url[:100]}...'
			)

			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='NetworkTimeout',
					message=f'Network request timed out after {self.network_timeout_seconds}s',
					details={
						'url': tracker.url,
						'method': tracker.method,
						'resource_type': tracker.resource_type,
						'elapsed_seconds': current_time - tracker.start_time,
					},
				)
			)

			# Remove from tracking
			del self._active_requests[request_id]

	async def _check_browser_health(self) -> None:
		"""Check if browser and pages are still responsive."""
		# Check browser connection
		if self.browser_session._browser and not self.browser_session._browser.is_connected():
			logger.error('[Watchdog] Browser disconnected unexpectedly')
			self.event_bus.dispatch(
				BrowserErrorEvent(error_type='BrowserDisconnected', message='Browser disconnected unexpectedly', details={})
			)
			# Exit the monitoring loop - don't try to stop from within the loop
			raise asyncio.CancelledError('Browser disconnected')

		# Check browser process if we have PID
		if self._browser_pid:
			try:
				import psutil

				proc = psutil.Process(self._browser_pid)
				if proc.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
					logger.error(f'[Watchdog] Browser process {self._browser_pid} has crashed')
					self.event_bus.dispatch(
						BrowserErrorEvent(
							error_type='BrowserProcessCrashed',
							message=f'Browser process {self._browser_pid} has crashed',
							details={'pid': self._browser_pid, 'status': proc.status()},
						)
					)
					await self._stop_monitoring()
					return
			except Exception:
				pass  # psutil not available or process doesn't exist

		# Check each page
		dead_pages = []
		unresponsive_pages = []

		if not self.browser_session._browser_context:
			return

		for page in list(self.browser_session._browser_context.pages):  # Copy to avoid modification during iteration
			try:
				if page.is_closed():
					dead_pages.append(page)
				# Check responsiveness for non-blank pages
				elif not self._is_new_tab_page(page.url):
					# Only check responsiveness occasionally to avoid overhead
					page_url = page.url
					last_check = self._last_responsive_checks.get(page_url, 0)
					if time.time() - last_check > 10:
						if not await self._is_page_responsive(page, timeout=2.0):
							unresponsive_pages.append(page)
						self._last_responsive_checks[page_url] = time.time()
			except Exception:
				# Page reference might be invalid
				dead_pages.append(page)

		# Remove dead pages
		for page in dead_pages:
			# Pages are managed by browser context, no need to remove manually
			pass

		# Report unresponsive pages
		for page in unresponsive_pages:
			logger.warning(f'[Watchdog] Page unresponsive: {page.url}')

			tab_index = self.browser_session.get_tab_index(page)
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='PageUnresponsive',
					message=f'Page JS engine unresponsive: {page.url}',
					details={
						'url': page.url,
						'tab_index': tab_index,
					},
				)
			)

	async def _is_page_responsive(self, page: Page, timeout: float = 5.0) -> bool:
		"""Check if a page is responsive by trying to evaluate simple JavaScript.

		Reused from main branch BrowserSession._is_page_responsive
		"""
		eval_task = None
		try:
			eval_task = asyncio.create_task(page.evaluate('1'))
			done, pending = await asyncio.wait([eval_task], timeout=timeout)

			if eval_task in done:
				try:
					await eval_task  # This will raise if the evaluation failed
					return True
				except Exception:
					return False
			else:
				# Timeout - the page is unresponsive
				return False
		except Exception:
			return False
		finally:
			# Always clean up the eval task
			if eval_task and not eval_task.done():
				eval_task.cancel()
				try:
					await eval_task
				except (asyncio.CancelledError, Exception):
					pass

	def _is_new_tab_page(self, url: str) -> bool:
		"""Check if URL is a new tab page."""
		return url in ['about:blank', 'chrome://new-tab-page/', 'chrome://newtab/']

	async def trigger_browser_crash(self) -> None:
		"""Trigger a browser crash for testing (requires CDP session)."""
		if not self._cdp_session:
			logger.warning('[Watchdog] No CDP session available for crash testing')
			return

		try:
			logger.warning('[Watchdog] Triggering browser crash for testing...')
			await self._cdp_session.send('Browser.crash')
		except Exception as e:
			logger.error(f'[Watchdog] Failed to trigger browser crash: {e}')

	async def trigger_gpu_crash(self) -> None:
		"""Trigger a GPU process crash for testing (requires CDP session)."""
		if not self._cdp_session:
			logger.warning('[Watchdog] No CDP session available for GPU crash testing')
			return

		try:
			logger.warning('[Watchdog] Triggering GPU crash for testing...')
			await self._cdp_session.send('Browser.crashGpuProcess')
		except Exception as e:
			logger.error(f'[Watchdog] Failed to trigger GPU crash: {e}')

	async def trigger_page_crash(self, page: Page) -> None:
		"""Trigger a page crash for testing."""
		try:
			logger.warning(f'[Watchdog] Triggering page crash for testing on: {page.url}')
			cdp = await page.context.new_cdp_session(page)
			await cdp.send('Page.crash')
			await cdp.detach()
		except Exception as e:
			logger.error(f'[Watchdog] Failed to trigger page crash: {e}')


# Fix Pydantic circular dependency - this will be called from session.py after BrowserSession is defined
