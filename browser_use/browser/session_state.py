"""BrowserSession state, logging, and reset helpers."""

from __future__ import annotations

import logging
from functools import cached_property
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from browser_use.browser.demo_mode import DemoMode
	from browser_use.browser.watchdogs.captcha_watchdog import CaptchaWaitResult

_LOGGED_UNIQUE_SESSION_IDS = set()
red = '\033[91m'
reset = '\033[0m'


class BrowserSessionStateMixin:
	"""Shared state helpers for BrowserSession."""

	@property
	def cdp_url(self: Any) -> str | None:
		"""CDP URL from browser profile."""
		return self.browser_profile.cdp_url

	@property
	def is_local(self: Any) -> bool:
		"""Whether this is a local browser instance from browser profile."""
		return self.browser_profile.is_local

	@property
	def is_cdp_connected(self: Any) -> bool:
		"""Check if the CDP WebSocket connection is alive and usable."""
		if self._cdp_client_root is None or self._cdp_client_root.ws is None:
			return False
		try:
			from websockets.protocol import State

			return self._cdp_client_root.ws.state is State.OPEN
		except Exception:
			return False

	async def wait_if_captcha_solving(self: Any, timeout: float | None = None) -> CaptchaWaitResult | None:
		"""Wait if a captcha is currently being solved by the browser proxy."""
		if self._captcha_watchdog is not None:
			return await self._captcha_watchdog.wait_if_captcha_solving(timeout=timeout)
		return None

	@property
	def is_reconnecting(self: Any) -> bool:
		"""Whether a WebSocket reconnection attempt is currently in progress."""
		return self._reconnecting

	@property
	def cloud_browser(self: Any) -> bool:
		"""Whether to use cloud browser service from browser profile."""
		return self.browser_profile.use_cloud

	@property
	def demo_mode(self: Any) -> DemoMode | None:
		"""Lazy init demo mode helper when enabled."""
		if not self.browser_profile.demo_mode:
			return None
		if self._demo_mode is None:
			from browser_use.browser.demo_mode import DemoMode

			self._demo_mode = DemoMode(self)
		return self._demo_mode

	@property
	def logger(self: Any) -> Any:
		"""Get instance-specific logger with session ID in the name."""
		return logging.getLogger(f'browser_use.{self}')

	@cached_property
	def _id_for_logs(self: Any) -> str:
		"""Get human-friendly semi-unique identifier for BrowserSession logs."""
		str_id = self.id[-4:]
		port_number = (self.cdp_url or 'no-cdp').rsplit(':', 1)[-1].split('/', 1)[0].strip()
		port_is_random = not port_number.startswith('922')
		port_is_unique_enough = port_number not in _LOGGED_UNIQUE_SESSION_IDS
		if port_number and port_number.isdigit() and port_is_random and port_is_unique_enough:
			_LOGGED_UNIQUE_SESSION_IDS.add(port_number)
			str_id = port_number
		return str_id

	@property
	def _tab_id_for_logs(self: Any) -> str:
		return self.agent_focus_target_id[-2:] if self.agent_focus_target_id else f'{red}--{reset}'

	def __repr__(self: Any) -> str:
		return f'BrowserSession🅑 {self._id_for_logs} 🅣 {self._tab_id_for_logs} (cdp_url={self.cdp_url}, profile={self.browser_profile})'

	def __str__(self: Any) -> str:
		return f'BrowserSession🅑 {self._id_for_logs} 🅣 {self._tab_id_for_logs}'

	async def reset(self: Any) -> None:
		"""Clear all cached CDP sessions with proper cleanup."""

		self._intentional_stop = True
		if self._reconnect_task and not self._reconnect_task.done():
			self._reconnect_task.cancel()
			self._reconnect_task = None
		self._reconnecting = False
		self._reconnect_event.set()

		cdp_status = 'connected' if self._cdp_client_root else 'not connected'
		session_mgr_status = 'exists' if self.session_manager else 'None'
		self.logger.debug(
			f'🔄 Resetting browser session (CDP: {cdp_status}, SessionManager: {session_mgr_status}, '
			f'focus: {self.agent_focus_target_id[-4:] if self.agent_focus_target_id else "None"})'
		)

		if self.session_manager:
			await self.session_manager.clear()
			self.session_manager = None

		if self._cdp_client_root:
			try:
				await self._cdp_client_root.stop()
				self.logger.debug('Closed CDP client WebSocket during reset')
			except Exception as e:
				self.logger.debug(f'Error closing CDP client during reset: {e}')

		self._cdp_client_root = None
		self._cached_browser_state_summary = None
		self._cached_selector_map.clear()
		self._downloaded_files.clear()
		self._dialog_listeners_registered.clear()

		self.agent_focus_target_id = None
		if self.is_local:
			self.browser_profile.cdp_url = None

		self._crash_watchdog = None
		self._downloads_watchdog = None
		self._aboutblank_watchdog = None
		self._security_watchdog = None
		self._storage_state_watchdog = None
		self._local_browser_watchdog = None
		self._default_action_watchdog = None
		self._dom_watchdog = None
		self._screenshot_watchdog = None
		self._permissions_watchdog = None
		self._recording_watchdog = None
		self._har_recording_watchdog = None
		self._captcha_watchdog = None
		self._watchdogs_attached = False
		if self._demo_mode:
			self._demo_mode.reset()
			self._demo_mode = None

		self._intentional_stop = False
		self.logger.info('✅ Browser session reset complete')
