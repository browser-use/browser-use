"""Lightweight BrowserSession subclass for the CLI daemon.

Skips watchdogs, event bus handlers, and auto-reconnect for ALL modes.
Launches browser if needed, then calls connect() directly.
All inherited methods (get_element_by_index, take_screenshot, etc.)
work because this IS a BrowserSession.
"""

from __future__ import annotations

import logging

import psutil

from browser_use.browser.session import BrowserSession

logger = logging.getLogger('browser_use.skill_cli.browser')


class CLIBrowserSession(BrowserSession):
	"""BrowserSession that skips watchdogs and event bus for all modes.

	For --connect: connects to existing Chrome via CDP URL.
	For managed Chromium: launches browser, gets CDP URL, connects.
	For cloud: provisions browser, gets CDP URL, connects.

	All three modes converge at connect() — no watchdogs, no event bus.
	"""

	_browser_process: psutil.Process | None = None  # type: ignore[assignment]

	async def start(self) -> None:
		"""Launch/provision browser if needed, then connect lightweight."""
		if self.cdp_url:
			# --connect or --cdp-url: CDP URL already known
			pass
		elif self.browser_profile.use_cloud:
			# Cloud: provision browser via API
			await self._provision_cloud_browser()
		else:
			# Managed Chromium: launch browser process
			await self._launch_local_browser()

		# All modes: lightweight CDP connection (no watchdogs)
		await self.connect()

		# Prevent heavy monitoring on future tabs
		if self.session_manager:

			async def _noop(cdp_session: object) -> None:
				pass

			self.session_manager._enable_page_monitoring = _noop  # type: ignore[assignment]

		# Disable auto-reconnect — daemon should die when CDP drops
		self._intentional_stop = True

		# Register popup/dialog handler so JS alerts don't freeze Chrome
		await self._register_dialog_handler()

	async def _register_dialog_handler(self) -> None:
		"""Register CDP handler to auto-dismiss JS dialogs (alert, confirm, prompt).

		Without this, any JS dialog freezes all CDP commands until manually dismissed.
		Messages are stored in _closed_popup_messages for inclusion in state output.
		"""
		import asyncio as _asyncio

		if not self._cdp_client_root:
			return

		async def handle_dialog(event_data: dict, session_id: str | None = None) -> None:
			try:
				dialog_type = event_data.get('type', 'alert')
				message = event_data.get('message', '')
				if message:
					self._closed_popup_messages.append(f'[{dialog_type}] {message}')
				# Accept alerts/confirms/beforeunload, dismiss prompts
				should_accept = dialog_type in ('alert', 'confirm', 'beforeunload')
				logger.info(f'Auto-{"accepting" if should_accept else "dismissing"} {dialog_type}: {message[:100]}')
				if not self._cdp_client_root:
					return
				await _asyncio.wait_for(
					self._cdp_client_root.send.Page.handleJavaScriptDialog(
						params={'accept': should_accept},
						session_id=session_id,
					),
					timeout=0.5,
				)
			except Exception:
				pass

		# Try to enable Page domain on root client (may fail — not all CDP targets support it)
		try:
			await self._cdp_client_root.send.Page.enable()
		except Exception:
			pass
		self._cdp_client_root.register.Page.javascriptDialogOpening(handle_dialog)  # type: ignore[arg-type]

	async def _launch_local_browser(self) -> None:
		"""Launch Chromium using LocalBrowserWatchdog's launch logic."""
		from bubus import EventBus

		from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog

		# Instantiate watchdog as plain object — NOT registered on event bus
		launcher = LocalBrowserWatchdog(event_bus=EventBus(), browser_session=self)
		process, cdp_url = await launcher._launch_browser()
		self._browser_process = process
		self.browser_profile.cdp_url = cdp_url
		logger.info(f'Launched browser (PID {process.pid}), CDP: {cdp_url}')

	async def _provision_cloud_browser(self) -> None:
		"""Provision a cloud browser and set the CDP URL."""
		import os

		from browser_use.browser.cloud.views import CreateBrowserRequest

		# Override cloud API base URL if set (CLI injects this into daemon env).
		# CloudBrowserClient expects the host URL (it appends /api/v2/... internally).
		cloud_base = os.environ.get('BROWSER_USE_CLOUD_BASE_URL')
		if cloud_base:
			self._cloud_browser_client.api_base_url = cloud_base.rstrip('/')

		# Ensure CLI has an API key from config.json before proceeding.
		from browser_use.skill_cli.config import get_config_value

		if not get_config_value('api_key'):
			from browser_use.browser.cloud.views import CloudBrowserAuthError

			raise CloudBrowserAuthError(
				'No API key configured. Run `browser-use cloud login <key>` or `browser-use cloud signup`.'
			)

		cloud_params = self.browser_profile.cloud_browser_params or CreateBrowserRequest()
		# Set recording from CLI config (defaults to True)
		from browser_use.skill_cli.config import get_config_value

		cloud_params.enable_recording = bool(get_config_value('cloud_connect_recording'))

		try:
			cloud_response = await self._cloud_browser_client.create_browser(cloud_params)
		except Exception as e:
			# If profile is invalid, create a new one and retry once
			if 'profile' in str(e).lower() or '422' in str(e):
				logger.info('Cloud profile invalid, creating new one and retrying')
				from browser_use.skill_cli.commands.cloud import _create_cloud_profile_inner

				api_key = get_config_value('api_key')
				if not api_key:
					raise
				new_profile_id = _create_cloud_profile_inner(str(api_key))
				cloud_params.profile_id = new_profile_id
				cloud_response = await self._cloud_browser_client.create_browser(cloud_params)
			else:
				raise
		self.browser_profile.cdp_url = cloud_response.cdpUrl
		self.browser_profile.is_local = False
		logger.info(f'Cloud browser provisioned, CDP: {cloud_response.cdpUrl}')

	async def stop(self) -> None:
		"""Disconnect from the browser.

		For --connect/--cdp-url: just close the websocket (we don't own the browser).
		For cloud: stop the remote browser via API before disconnecting.
		"""
		self._intentional_stop = True
		# Stop cloud browser if we provisioned one
		if self.browser_profile.use_cloud and self._cloud_browser_client.current_session_id:
			try:
				import asyncio as _asyncio

				await _asyncio.wait_for(self._cloud_browser_client.stop_browser(), timeout=5.0)
			except Exception as e:
				logger.debug(f'Error stopping cloud browser: {e}')
		if self._cdp_client_root:
			try:
				await self._cdp_client_root.stop()
			except Exception as e:
				logger.debug(f'Error closing CDP client: {e}')
			self._cdp_client_root = None  # type: ignore[assignment]
		if self.session_manager:
			try:
				await self.session_manager.clear()
			except Exception as e:
				logger.debug(f'Error clearing session manager: {e}')
			self.session_manager = None
		self.agent_focus_target_id = None
		self._cached_selector_map.clear()

	async def kill(self) -> None:
		"""Send Browser.close to kill the browser, then disconnect.

		For managed Chromium: sends Browser.close CDP command + terminates process.
		"""
		if self._cdp_client_root:
			try:
				await self._cdp_client_root.send.Browser.close()
			except Exception:
				pass
		await self.stop()
		# Force kill the process if we launched it and it's still alive
		if self._browser_process:
			try:
				if self._browser_process.is_running():
					self._browser_process.terminate()
					self._browser_process.wait(timeout=5)
			except Exception:
				try:
					self._browser_process.kill()
				except Exception:
					pass
			self._browser_process = None

	@property
	def is_cdp_connected(self) -> bool:
		"""Check if CDP WebSocket connection is alive."""
		if self._cdp_client_root is None or self._cdp_client_root.ws is None:
			return False
		try:
			from websockets.protocol import State

			return self._cdp_client_root.ws.state is State.OPEN
		except Exception:
			return False
