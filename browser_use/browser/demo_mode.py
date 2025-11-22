"""Demo mode helper for injecting and updating the in-browser log panel."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from browser_use.browser.demo_panel_scripts import get_full_panel_script, get_last_panel_script
from browser_use.browser.session import BrowserSession


class DemoMode:
	VALID_LEVELS = {'info', 'action', 'thought', 'error', 'success', 'warning'}
	MAX_BUFFERED_MESSAGES = 100

	def __init__(self, session: BrowserSession):
		self.session = session
		self.logger = logging.getLogger(f'{__name__}.DemoMode')
		self._script_source: str | None = None
		self._panel_ready = False
		self._lock = asyncio.Lock()
		self._script_identifiers: dict[str, str] = {}
		self._message_buffer: deque[dict[str, Any]] = deque(maxlen=self.MAX_BUFFERED_MESSAGES)

	def reset(self) -> None:
		self._script_source = None
		self._script_identifiers.clear()
		self._message_buffer.clear()
		self._panel_ready = False

	def _load_script(self) -> str:
		if self._script_source is None:
			session_id = self.session.id
			accent_color = '#fe750e'  # Default accent color
			display_mode = self.session.browser_profile.demo_mode_display

			if display_mode == 'last':
				self._script_source = get_last_panel_script(session_id, accent_color)
			else:
				self._script_source = get_full_panel_script(session_id, accent_color)

			self.logger.debug(f'Loaded {display_mode} mode script for session {session_id}')

		return self._script_source

	async def ensure_ready(self) -> None:
		"""Add init script and inject overlay into currently open pages."""
		if not self.session.browser_profile.demo_mode:
			return
		if self.session._cdp_client_root is None:
			raise RuntimeError('Root CDP client not initialized')

		async with self._lock:
			script = self._load_script()
			target_ids = await self._get_relevant_target_ids()
			for target_id in target_ids:
				await self._ensure_script_for_target(target_id, script)

			self._panel_ready = True
			self.logger.debug('Demo overlay injected successfully')

	async def register_new_target(self, target_id: str) -> None:
		"""Ensure demo overlay is attached to a newly created target."""
		await self.refresh_target(target_id)

	async def refresh_target(self, target_id: str) -> None:
		"""Reinstate the overlay and replay logs for the given target."""
		if not self.session.browser_profile.demo_mode:
			return
		if self.session._cdp_client_root is None:
			return

		async with self._lock:
			script = self._load_script()
			if target_id not in self._script_identifiers:
				await self._ensure_script_for_target(target_id, script)
			else:
				await self._reinstate_target(target_id, script)
			self._panel_ready = True

	def unregister_target(self, target_id: str) -> None:
		"""Stop tracking a target after it closes."""
		self._script_identifiers.pop(target_id, None)

	async def send_log(self, message: str, level: str = 'info', metadata: dict[str, Any] | None = None) -> None:
		"""Send a log entry to the in-browser panel."""
		if not message or not self.session.browser_profile.demo_mode:
			return

		try:
			await self.ensure_ready()
		except Exception as exc:
			self.logger.warning(f'Failed to ensure demo mode is ready: {exc}')
			return

		if self.session.agent_focus_target_id is None:
			self.logger.debug('Cannot send demo log: no active target')
			return

		level_value = level.lower()
		if level_value not in self.VALID_LEVELS:
			level_value = 'info'

		metadata = dict(metadata) if metadata else {}

		payload = {
			'message': message,
			'level': level_value,
			'metadata': metadata,
			'timestamp': datetime.now(timezone.utc).isoformat(),
		}

		self._message_buffer.append(payload)

		script = self._build_event_expression(json.dumps(payload, ensure_ascii=False))

		try:
			session = await self.session.get_or_create_cdp_session(target_id=None, focus=False)
		except Exception as exc:
			self.logger.debug(f'Cannot acquire CDP session for demo log: {exc}')
			return

		try:
			await session.cdp_client.send.Runtime.evaluate(
				params={'expression': script, 'awaitPromise': False}, session_id=session.session_id
			)
		except Exception as exc:
			self.logger.debug(f'Failed to send demo log: {exc}')

	def _build_event_expression(self, payload: str) -> str:
		return f"""
(() => {{
	const detail = {payload};
	const event = new CustomEvent('browser-use-log', {{ detail }});
	window.dispatchEvent(event);
}})();
""".strip()

	async def _get_relevant_target_ids(self) -> list[str]:
		targets = await self.session._cdp_get_all_pages(  # - intentional private access
			include_http=True,
			include_about=True,
			include_pages=True,
			include_iframes=False,
			include_workers=False,
			include_chrome=False,
			include_chrome_extensions=False,
			include_chrome_error=False,
		)

		target_ids = [t['targetId'] for t in targets]
		if not target_ids and self.session.agent_focus_target_id:
			target_ids = [self.session.agent_focus_target_id]
		return target_ids

	async def _ensure_script_for_target(self, target_id: str, script: str) -> None:
		if target_id in self._script_identifiers:
			return

		try:
			identifier = await self.session._cdp_add_init_script(script, target_id=target_id)
			self._script_identifiers[target_id] = identifier
		except Exception as exc:
			self.logger.debug(f'Failed to register demo overlay script for {target_id}: {exc}')
			return

		await self._reinstate_target(target_id, script)

	async def _reinstate_target(self, target_id: str, script: str) -> None:
		try:
			await self._inject_into_target(target_id, script)
		except Exception as exc:
			self.logger.debug(f'Failed to inject demo overlay into {target_id}: {exc}')
			return

		try:
			await self._replay_buffer_to_target(target_id)
		except Exception as exc:
			self.logger.debug(f'Failed to replay demo logs into {target_id}: {exc}')

	async def _inject_into_target(self, target_id: str, script: str) -> None:
		session = await self.session.get_or_create_cdp_session(target_id=target_id, focus=False)
		await session.cdp_client.send.Runtime.evaluate(
			params={'expression': script, 'awaitPromise': False},
			session_id=session.session_id,
		)

	async def _replay_buffer_to_target(self, target_id: str) -> None:
		if not self._message_buffer:
			return

		try:
			session = await self.session.get_or_create_cdp_session(target_id=target_id, focus=False)
		except Exception as exc:
			self.logger.debug(f'Cannot replay demo logs to {target_id}: {exc}')
			return

		for payload in self._message_buffer:
			script = self._build_event_expression(json.dumps(payload, ensure_ascii=False))
			try:
				await session.cdp_client.send.Runtime.evaluate(
					params={'expression': script, 'awaitPromise': False},
					session_id=session.session_id,
				)
			except Exception as exc:
				self.logger.debug(f'Failed to replay demo log to {target_id}: {exc}')
