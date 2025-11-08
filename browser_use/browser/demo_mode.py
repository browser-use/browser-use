"""Demo mode helper for injecting and updating the in-browser log panel."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession


class DemoMode:
	"""Encapsulates browser overlay injection and log broadcasting for demo mode."""

	VALID_LEVELS = {'info', 'action', 'thought', 'error', 'success', 'warning'}

	def __init__(self, session: BrowserSession):
		self.session = session
		self.logger = logging.getLogger(f'{__name__}.DemoMode')
		self._script_identifier: str | None = None
		self._script_source: str | None = None
		self._panel_ready = False
		self._lock = asyncio.Lock()

	def reset(self) -> None:
		self._script_identifier = None
		self._panel_ready = False

	def _load_script(self) -> str:
		if self._script_source is None:
			script_path = Path(__file__).with_name('demo_panel.js')
			self._script_source = script_path.read_text(encoding='utf-8')
		
		# Replace placeholder with actual session ID
		session_id = self.session.id
		script_with_session_id = self._script_source.replace('__BROWSER_USE_SESSION_ID_PLACEHOLDER__', session_id)
		self.logger.debug(f'Injecting session ID {session_id} into demo panel script')
		return script_with_session_id

	async def ensure_ready(self) -> None:
		"""Add init script and inject overlay into currently open pages."""
		if not self.session.browser_profile.demo_mode:
			return
		if self.session._cdp_client_root is None:
			raise RuntimeError('Root CDP client not initialized')

		async with self._lock:
			script = self._load_script()

			if self._script_identifier is None:
				self._script_identifier = await self.session._cdp_add_init_script(script)
				self.logger.debug('Added auto-injection script for demo overlay')

			await self._inject_into_open_pages(script)
			self._panel_ready = True
			self.logger.debug('Demo overlay injected successfully')

	async def send_log(self, message: str, level: str = 'info', metadata: dict[str, Any] | None = None) -> None:
		"""Send a log entry to the in-browser panel."""
		if not message or not self.session.browser_profile.demo_mode:
			return

		try:
			await self.ensure_ready()
		except Exception as exc:
			self.logger.warning(f'Failed to ensure demo mode is ready: {exc}')
			return

		if self.session.agent_focus is None:
			self.logger.debug('Cannot send demo log: no active target')
			return

		level_value = level.lower()
		if level_value not in self.VALID_LEVELS:
			level_value = 'info'

		payload = {
			'message': message,
			'level': level_value,
			'metadata': metadata or {},
			'timestamp': datetime.now(timezone.utc).isoformat(),
		}

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

	async def _inject_into_open_pages(self, script: str) -> None:
		targets = await self.session._cdp_get_all_pages(  # noqa: SLF001 - intentional private access
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
		if not target_ids and self.session.agent_focus:
			target_ids = [self.session.agent_focus.target_id]

		for target_id in target_ids:
			try:
				await self._inject_into_target(target_id, script)
			except Exception as exc:
				self.logger.debug(f'Failed to inject demo overlay into {target_id}: {exc}')

	async def _inject_into_target(self, target_id: str, script: str) -> None:
		session = await self.session.get_or_create_cdp_session(target_id=target_id, focus=False)
		await session.cdp_client.send.Runtime.evaluate(
			params={'expression': script, 'awaitPromise': False},
			session_id=session.session_id,
		)
