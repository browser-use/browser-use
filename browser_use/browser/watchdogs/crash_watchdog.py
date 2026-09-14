"""Browser watchdog for monitoring crashes and network timeouts using CDP."""

import asyncio
import time
from typing import TYPE_CHECKING, ClassVar

import psutil
from bubus import BaseEvent
from cdp_use.cdp.target import SessionID, TargetID
from cdp_use.cdp.target.events import TargetCrashedEvent
from pydantic import Field, PrivateAttr

from browser_use.browser.events import (
	BrowserConnectedEvent,
	BrowserErrorEvent,
	BrowserStoppedEvent,
	TabClosedEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.utils import create_task_with_error_handling

if TYPE_CHECKING:
	pass


class NetworkRequestTracker:
	"""Tracks ongoing network requests."""

	def __init__(self, request_id: str, start_time: float, url: str, method: str, resource_type: str | None = None):
		self.request_id = request_id
		self.start_time = start_time
		self.url = url
		self.method = method
		self.resource_type = resource_type


class CrashWatchdog(BaseWatchdog):
	"""Monitors browser health for crashes and network timeouts using CDP."""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		BrowserConnectedEvent,
		BrowserStoppedEvent,
		TabCreatedEvent,
		TabClosedEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent]]] = [BrowserErrorEvent]

	# Configuration
	network_timeout_seconds: float = Field(default=10.0)
	check_interval_seconds: float = Field(default=5.0)  # Reduced frequency to reduce noise
	crash_recovery_timeout_seconds: float = Field(default=10.0)  # Per-CDP-call budget while recovering a crashed target
	enable_periodic_health_checks: bool = Field(default=False)  # Opt-in polling loop; crash handling is always on

	# Private state
	_active_requests: dict[str, NetworkRequestTracker] = PrivateAttr(default_factory=dict)
	_monitoring_task: asyncio.Task | None = PrivateAttr(default=None)
	_last_responsive_checks: dict[str, float] = PrivateAttr(default_factory=dict)  # target_url -> timestamp
	_cdp_event_tasks: set[asyncio.Task] = PrivateAttr(default_factory=set)  # Track CDP event handler tasks
	_crash_listener_registered: bool = PrivateAttr(default=False)  # Browser-wide Target.targetCrashed handler installed
	_crashed_targets: set[str] = PrivateAttr(default_factory=set)  # Crashes currently being recovered (de-dupes retries)

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""Start monitoring when browser is connected."""
		# logger.debug('[CrashWatchdog] Browser connected event received, beginning monitoring')

		# Register the crash listener up front so the tab the browser starts with is covered.
		# It previously only got registered from on_TabCreatedEvent, which never fires for the
		# initial tab, leaving the agent's very first page unmonitored for its whole lifetime.
		self._register_crash_listener()

		# The periodic responsiveness/network-timeout poll is opt-in; crash handling above is not.
		if self.enable_periodic_health_checks:
			create_task_with_error_handling(
				self._start_monitoring(), name='start_crash_monitoring', logger_instance=self.logger, suppress_exceptions=True
			)
		# logger.debug(f'[CrashWatchdog] Monitoring task started: {self._monitoring_task and not self._monitoring_task.done()}')

	async def on_BrowserStoppedEvent(self, event: BrowserStoppedEvent) -> None:
		"""Stop monitoring when browser stops."""
		# logger.debug('[CrashWatchdog] Browser stopped, ending monitoring')
		await self._stop_monitoring()

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Ensure crash monitoring is active. Covered by a single browser-wide listener."""
		self._register_crash_listener()

	async def on_TabClosedEvent(self, event: TabClosedEvent) -> None:
		"""Clean up tracking when tab closes."""
		self._crashed_targets.discard(event.target_id)

	def _register_crash_listener(self) -> None:
		"""Register the browser-wide `Target.targetCrashed` handler exactly once.

		`Target.targetCrashed` is a browser-level event: it is delivered with session_id=None
		and carries the crashed `targetId` in its payload. Every CDPSession in this codebase
		shares a single underlying CDP client, so the previous per-target registration added a
		*duplicate global* handler for each tab, and each of those handlers ignored the payload
		and blamed the `target_id` captured in its closure. With three tabs open, one crash
		therefore fired three handlers that between them reloaded two perfectly healthy tabs and
		misattributed the crash. Register once, and trust the payload.
		"""
		if self._crash_listener_registered:
			return

		cdp_client = self.browser_session.cdp_client
		if cdp_client is None:
			self.logger.debug('[CrashWatchdog] No CDP client yet, deferring crash listener registration')
			return

		def on_target_crashed(event: TargetCrashedEvent, session_id: SessionID | None = None):
			crashed_target_id = event.get('targetId')
			if not crashed_target_id:
				self.logger.warning(f'[CrashWatchdog] Target.targetCrashed without targetId: {event}')
				return

			task = create_task_with_error_handling(
				self._on_target_crash_cdp(crashed_target_id),
				name='handle_target_crash',
				logger_instance=self.logger,
				suppress_exceptions=True,
			)
			self._cdp_event_tasks.add(task)
			task.add_done_callback(lambda t: self._cdp_event_tasks.discard(t))

		cdp_client.register.Target.targetCrashed(on_target_crashed)
		self._crash_listener_registered = True
		self.logger.debug('[CrashWatchdog] Registered browser-wide Target.targetCrashed listener')

	async def _on_request_cdp(self, event: dict) -> None:
		"""Track new network request from CDP event."""
		request_id = event.get('requestId', '')
		request = event.get('request', {})

		self._active_requests[request_id] = NetworkRequestTracker(
			request_id=request_id,
			start_time=time.time(),
			url=request.get('url', ''),
			method=request.get('method', ''),
			resource_type=event.get('type'),
		)
		# logger.debug(f'[CrashWatchdog] Tracking request: {request.get("method", "")} {request.get("url", "")[:50]}...')

	def _on_response_cdp(self, event: dict) -> None:
		"""Remove request from tracking on response."""
		request_id = event.get('requestId', '')
		if request_id in self._active_requests:
			elapsed = time.time() - self._active_requests[request_id].start_time
			response = event.get('response', {})
			self.logger.debug(f'[CrashWatchdog] Request completed in {elapsed:.2f}s: {response.get("url", "")[:50]}...')
			# Don't remove yet - wait for loadingFinished

	def _on_request_failed_cdp(self, event: dict) -> None:
		"""Remove request from tracking on failure."""
		request_id = event.get('requestId', '')
		if request_id in self._active_requests:
			elapsed = time.time() - self._active_requests[request_id].start_time
			self.logger.debug(
				f'[CrashWatchdog] Request failed after {elapsed:.2f}s: {self._active_requests[request_id].url[:50]}...'
			)
			del self._active_requests[request_id]

	def _on_request_finished_cdp(self, event: dict) -> None:
		"""Remove request from tracking when loading is finished."""
		request_id = event.get('requestId', '')
		self._active_requests.pop(request_id, None)

	async def _on_target_crash_cdp(self, target_id: TargetID) -> None:
		"""Handle target crash detected via CDP.

		A renderer crash (OOM, WebGL context loss, sad-tab) is *not* a target detach: Chrome
		emits `Target.targetCrashed` but keeps the target attached and in the target list, so
		`SessionManager._handle_target_detached` — and therefore its auto-recovery — never runs.
		Waiting for a detach event that never arrives is what left the agent looping over
		'element not found' against a dead renderer until it burned its whole step budget.

		So recover here instead: reload the crashed target (Chrome spawns a fresh renderer for
		it), verify the new renderer answers, and only fall back to switching/creating a tab if
		that fails.
		"""
		if target_id in self._crashed_targets:
			# Chrome can emit targetCrashed more than once for the same death; don't stack recoveries.
			self.logger.debug(f'[CrashWatchdog] Recovery already in progress for {target_id[:8]}..., ignoring')
			return

		self._crashed_targets.add(target_id)
		try:
			await self._handle_crash(target_id)
		finally:
			self._crashed_targets.discard(target_id)

	async def _handle_crash(self, target_id: TargetID) -> None:
		target = self.browser_session.session_manager.get_target(target_id)
		url = target.url if target else None

		is_agent_focus = bool(
			self.browser_session.agent_focus_target_id and target_id == self.browser_session.agent_focus_target_id
		)

		self.logger.error(f'[CrashWatchdog] 💥 Target crashed: {url or target_id[:8]} (agent_focus={is_agent_focus})')

		recovered = await self._recover_crashed_target(target_id)

		if not recovered and is_agent_focus:
			# The tab itself is unrecoverable — hand off to SessionManager, which switches to
			# another page target or opens a fresh one.
			recovered = await self.browser_session.session_manager.recover_agent_focus(target_id)

		if recovered:
			self.logger.info(f'[CrashWatchdog] ✅ Recovered from crash of {url or target_id[:8]}')
		else:
			self.logger.error(
				f'[CrashWatchdog] ❌ Could not recover crashed target {url or target_id[:8]} - '
				f'subsequent actions on this tab will fail'
			)

		# Emit browser error event so the agent surfaces the crash as the root cause instead of
		# reporting a stream of misleading 'element not found' errors.
		self.event_bus.dispatch(
			BrowserErrorEvent(
				error_type='TargetCrash',
				message=(
					f'Target crashed: {target_id}' + (' (recovered by reloading the page)' if recovered else ' (recovery failed)')
				),
				details={
					'url': url,
					'target_id': target_id,
					'was_agent_focus': is_agent_focus,
					'recovered': recovered,
				},
			)
		)

	async def _recover_crashed_target(self, target_id: TargetID) -> bool:
		"""Reload a crashed target to respawn its renderer.

		Returns True only if the target answers a CDP round-trip afterwards, so a reload that
		silently lands on another dead renderer is still reported as a failure.
		"""
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)
		except Exception as e:
			self.logger.warning(f'[CrashWatchdog] No CDP session for crashed target {target_id[:8]}...: {e}')
			return False

		try:
			await asyncio.wait_for(
				cdp_session.cdp_client.send.Page.reload(params={'ignoreCache': False}, session_id=cdp_session.session_id),
				timeout=self.crash_recovery_timeout_seconds,
			)
		except Exception as e:
			self.logger.warning(f'[CrashWatchdog] Reload of crashed target {target_id[:8]}... failed: {e}')
			return False

		try:
			await asyncio.wait_for(
				cdp_session.cdp_client.send.Runtime.evaluate(
					params={'expression': '1', 'returnByValue': True}, session_id=cdp_session.session_id
				),
				timeout=self.crash_recovery_timeout_seconds,
			)
		except Exception as e:
			self.logger.warning(f'[CrashWatchdog] Target {target_id[:8]}... still unresponsive after reload: {e}')
			return False

		return True

	async def _start_monitoring(self) -> None:
		"""Start the monitoring loop."""
		assert self.browser_session.cdp_client is not None, 'Root CDP client not initialized - browser may not be connected yet'

		if self._monitoring_task and not self._monitoring_task.done():
			# logger.info('[CrashWatchdog] Monitoring already running')
			return

		self._monitoring_task = create_task_with_error_handling(
			self._monitoring_loop(), name='crash_monitoring_loop', logger_instance=self.logger, suppress_exceptions=True
		)
		# logger.debug('[CrashWatchdog] Monitoring loop created and started')

	async def _stop_monitoring(self) -> None:
		"""Stop the monitoring loop and clean up all tracking."""
		if self._monitoring_task and not self._monitoring_task.done():
			self._monitoring_task.cancel()
			try:
				await self._monitoring_task
			except asyncio.CancelledError:
				pass
			self.logger.debug('[CrashWatchdog] Monitoring loop stopped')

		# Cancel all CDP event handler tasks
		for task in list(self._cdp_event_tasks):
			if not task.done():
				task.cancel()
		# Wait for all tasks to complete cancellation
		if self._cdp_event_tasks:
			await asyncio.gather(*self._cdp_event_tasks, return_exceptions=True)
		self._cdp_event_tasks.clear()

		# Clear all tracking
		self._active_requests.clear()
		self._crashed_targets.clear()
		self._last_responsive_checks.clear()
		# The crash listener lives on the CDP client, which is torn down with the browser; a
		# reconnect builds a new client, so allow it to be registered again.
		self._crash_listener_registered = False

	async def _monitoring_loop(self) -> None:
		"""Main monitoring loop."""
		await asyncio.sleep(10)  # give browser time to start up and load the first page after first LLM call
		while True:
			try:
				await self._check_network_timeouts()
				await self._check_browser_health()
				await asyncio.sleep(self.check_interval_seconds)
			except asyncio.CancelledError:
				break
			except Exception as e:
				self.logger.error(f'[CrashWatchdog] Error in monitoring loop: {e}')

	async def _check_network_timeouts(self) -> None:
		"""Check for network requests exceeding timeout."""
		current_time = time.time()
		timed_out_requests = []

		# Debug logging
		if self._active_requests:
			self.logger.debug(
				f'[CrashWatchdog] Checking {len(self._active_requests)} active requests for timeouts (threshold: {self.network_timeout_seconds}s)'
			)

		for request_id, tracker in self._active_requests.items():
			elapsed = current_time - tracker.start_time
			self.logger.debug(
				f'[CrashWatchdog] Request {tracker.url[:30]}... elapsed: {elapsed:.1f}s, timeout: {self.network_timeout_seconds}s'
			)
			if elapsed >= self.network_timeout_seconds:
				timed_out_requests.append((request_id, tracker))

		# Emit events for timed out requests
		for request_id, tracker in timed_out_requests:
			self.logger.warning(
				f'[CrashWatchdog] Network request timeout after {self.network_timeout_seconds}s: '
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
		"""Check if browser and targets are still responsive."""

		try:
			self.logger.debug(f'[CrashWatchdog] Checking browser health for target {self.browser_session.agent_focus_target_id}')
			cdp_session = await self.browser_session.get_or_create_cdp_session()

			for target in self.browser_session.session_manager.get_all_page_targets():
				if self._is_new_tab_page(target.url) and target.url != 'about:blank':
					self.logger.debug(f'[CrashWatchdog] Redirecting chrome://new-tab-page/ to about:blank {target.url}')
					cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target.target_id)
					await cdp_session.cdp_client.send.Page.navigate(
						params={'url': 'about:blank'}, session_id=cdp_session.session_id
					)

			# Quick ping to check if session is alive
			self.logger.debug(f'[CrashWatchdog] Attempting to run simple JS test expression in session {cdp_session} 1+1')
			await asyncio.wait_for(
				cdp_session.cdp_client.send.Runtime.evaluate(params={'expression': '1+1'}, session_id=cdp_session.session_id),
				timeout=1.0,
			)
			self.logger.debug(
				f'[CrashWatchdog] Browser health check passed for target {self.browser_session.agent_focus_target_id}'
			)
		except Exception as e:
			self.logger.error(
				f'[CrashWatchdog] ❌ Crashed/unresponsive session detected for target {self.browser_session.agent_focus_target_id} '
				f'error: {type(e).__name__}: {e} (Chrome will send detach event, SessionManager will auto-recover)'
			)

		# Check browser process if we have PID
		if self.browser_session._local_browser_watchdog and (proc := self.browser_session._local_browser_watchdog._subprocess):
			try:
				if proc.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
					self.logger.error(f'[CrashWatchdog] Browser process {proc.pid} has crashed')

					# Browser process crashed - SessionManager will clean up via detach events
					# Just dispatch error event and stop monitoring
					self.event_bus.dispatch(
						BrowserErrorEvent(
							error_type='BrowserProcessCrashed',
							message=f'Browser process {proc.pid} has crashed',
							details={'pid': proc.pid, 'status': proc.status()},
						)
					)

					self.logger.warning('[CrashWatchdog] Browser process dead - stopping health monitoring')
					await self._stop_monitoring()
					return
			except Exception:
				pass  # psutil not available or process doesn't exist

	@staticmethod
	def _is_new_tab_page(url: str) -> bool:
		"""Check if URL is a new tab page."""
		return url in ['about:blank', 'chrome://new-tab-page/', 'chrome://newtab/']
