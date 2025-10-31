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

	# Private state
	_active_requests: dict[str, NetworkRequestTracker] = PrivateAttr(default_factory=dict)
	_monitoring_task: asyncio.Task | None = PrivateAttr(default=None)
	_last_responsive_checks: dict[str, float] = PrivateAttr(default_factory=dict)  # target_url -> timestamp
	_cdp_event_tasks: set[asyncio.Task] = PrivateAttr(default_factory=set)  # Track CDP event handler tasks
	_targets_with_listeners: set[str] = PrivateAttr(default_factory=set)  # Track targets that already have event listeners

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""Start monitoring when browser is connected."""
		# logger.debug('[CrashWatchdog] Browser connected event received, beginning monitoring')

		asyncio.create_task(self._start_monitoring())
		# logger.debug(f'[CrashWatchdog] Monitoring task started: {self._monitoring_task and not self._monitoring_task.done()}')

	async def on_BrowserStoppedEvent(self, event: BrowserStoppedEvent) -> None:
		"""Stop monitoring when browser stops."""
		# logger.debug('[CrashWatchdog] Browser stopped, ending monitoring')
		await self._stop_monitoring()

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Attach to new tab."""
		assert self.browser_session.agent_focus is not None, 'No current target ID'
		await self.attach_to_target(self.browser_session.agent_focus.target_id)

	async def on_TabClosedEvent(self, event: TabClosedEvent) -> None:
		"""Clean up tracking when tab closes."""
		# Remove target from listener tracking to prevent memory leak
		if event.target_id in self._targets_with_listeners:
			self._targets_with_listeners.discard(event.target_id)
			self.logger.debug(f'[CrashWatchdog] Removed target {event.target_id[:8]}... from monitoring')

	async def attach_to_target(self, target_id: TargetID) -> None:
		"""Set up crash monitoring for a specific target using CDP."""
		try:
			# Check if we already have listeners for this target
			if target_id in self._targets_with_listeners:
				self.logger.debug(f'[CrashWatchdog] Event listeners already exist for target: {target_id[:8]}...')
				return

			# Create temporary session for monitoring without switching focus
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			# Register crash event handler
			def on_target_crashed(event: TargetCrashedEvent, session_id: SessionID | None = None):
				# Create and track the task
				task = asyncio.create_task(self._on_target_crash_cdp(target_id))
				self._cdp_event_tasks.add(task)
				# Remove from set when done
				task.add_done_callback(lambda t: self._cdp_event_tasks.discard(t))

			cdp_session.cdp_client.register.Target.targetCrashed(on_target_crashed)

			# Track that we've added listeners to this target
			self._targets_with_listeners.add(target_id)

			# Get target info for logging
			targets = await cdp_session.cdp_client.send.Target.getTargets()
			target_info = next((t for t in targets['targetInfos'] if t['targetId'] == target_id), None)
			if target_info:
				self.logger.debug(f'[CrashWatchdog] Added target to monitoring: {target_info.get("url", "unknown")}')

		except Exception as e:
			self.logger.warning(f'[CrashWatchdog] Failed to attach to target {target_id}: {e}')

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
		"""Handle target crash detected via CDP."""
		self.logger.debug(f'[CrashWatchdog] Target crashed: {target_id[:8]}..., waiting for detach event')

		# Get target info for logging
		cdp_client = self.browser_session.cdp_client
		targets = await cdp_client.send.Target.getTargets()
		target_info = next((t for t in targets['targetInfos'] if t['targetId'] == target_id), None)

		is_agent_focus = (
			target_info
			and self.browser_session.agent_focus
			and target_info['targetId'] == self.browser_session.agent_focus.target_id
		)

		if is_agent_focus and target_info:
			self.logger.error(
				f'[CrashWatchdog] 💥 Agent focus tab crashed: {target_info.get("url", "unknown")} '
				f'(SessionManager will auto-recover)'
			)

		# Emit browser error event
		self.event_bus.dispatch(
			BrowserErrorEvent(
				error_type='TargetCrash',
				message=f'Target crashed: {target_id}',
				details={
					'url': target_info.get('url') if target_info else None,
					'target_id': target_id,
					'was_agent_focus': is_agent_focus,
				},
			)
		)

	async def _start_monitoring(self) -> None:
		"""Start the monitoring loop."""
		assert self.browser_session.cdp_client is not None, 'Root CDP client not initialized - browser may not be connected yet'

		if self._monitoring_task and not self._monitoring_task.done():
			# logger.info('[CrashWatchdog] Monitoring already running')
			return

		self._monitoring_task = asyncio.create_task(self._monitoring_loop())
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
		self._targets_with_listeners.clear()
		self._last_responsive_checks.clear()

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
			self.logger.debug(f'[CrashWatchdog] Checking browser health for target {self.browser_session.agent_focus}')
			cdp_session = await self.browser_session.get_or_create_cdp_session()

			for target in (await self.browser_session.cdp_client.send.Target.getTargets()).get('targetInfos', []):
				if target.get('type') == 'page':
					cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target.get('targetId'))
					if self._is_new_tab_page(target.get('url')) and target.get('url') != 'about:blank':
						self.logger.debug(
							f'[CrashWatchdog] Redirecting chrome://new-tab-page/ to about:blank {target.get("url")}'
						)
						await cdp_session.cdp_client.send.Page.navigate(
							params={'url': 'about:blank'}, session_id=cdp_session.session_id
						)

			# Quick ping to check if session is alive
			self.logger.debug(f'[CrashWatchdog] Attempting to run simple JS test expression in session {cdp_session} 1+1')
			await asyncio.wait_for(
				cdp_session.cdp_client.send.Runtime.evaluate(params={'expression': '1+1'}, session_id=cdp_session.session_id),
				timeout=1.0,
			)
			self.logger.debug(f'[CrashWatchdog] Browser health check passed for target {self.browser_session.agent_focus}')
		except Exception as e:
			self.logger.error(
				f'[CrashWatchdog] ❌ Crashed/unresponsive session detected for target {self.browser_session.agent_focus} '
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
