"""Watchdog to handle captcha solving events and pause agent execution.

This watchdog listens to custom CDP events that your environment emits:
- BrowserUse.captchaSolverStarted
- BrowserUse.captchaSolverFinished

When captcha events are received, this watchdog pauses the agent by setting
browser_session.agent_paused_for_captcha flag.
"""

# @file purpose: Defines a watchdog that handles captcha events and pauses agent execution

from typing import Any, ClassVar

from bubus import BaseEvent
from pydantic import PrivateAttr

from browser_use.browser.events import BrowserConnectedEvent
from browser_use.browser.watchdog_base import BaseWatchdog


class CaptchaWatchdog(BaseWatchdog):
	"""Handles captcha solving events and pauses agent execution."""

	LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = [
		BrowserConnectedEvent,  # To register CDP listeners
	]
	EMITS: ClassVar[list[type[BaseEvent[Any]]]] = []

	_cdp_listeners_registered: bool = PrivateAttr(default=False)

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""Register CDP event listeners when browser connects."""
		if self._cdp_listeners_registered:
			return

		try:
			cdp_client = self.browser_session.cdp_client

			# Define CDP event handlers
			def on_captcha_started(event_data: dict, session_id: str | None = None) -> None:
				"""Handle CDP captchaSolverStarted event."""
				vendor = event_data.get('vendor', 'unknown')
				url = event_data.get('url', '')
				target_id = event_data.get('targetId', '')

				self.logger.info(
					f'🧩 Captcha solver started: vendor={vendor} url={url} target=...{target_id[-4:] if target_id else "???"}'
				)

				# Pause the agent
				self.browser_session.agent_paused_for_captcha = True

			def on_captcha_finished(event_data: dict, session_id: str | None = None) -> None:
				"""Handle CDP captchaSolverFinished event."""
				vendor = event_data.get('vendor', 'unknown')
				url = event_data.get('url', '')
				duration_ms = event_data.get('durationMs', 0)
				target_id = event_data.get('targetId', '')

				self.logger.info(
					f'✅ Captcha solver finished: vendor={vendor} url={url} '
					f'duration={duration_ms}ms target=...{target_id[-4:] if target_id else "???"}'
				)

				# Resume the agent
				self.browser_session.agent_paused_for_captcha = False

			# Register the CDP event listeners for BrowserUse domain
			cdp_client.register.BrowserUse.captchaSolverStarted(on_captcha_started)  # type: ignore[arg-type]
			cdp_client.register.BrowserUse.captchaSolverFinished(on_captcha_finished)  # type: ignore[arg-type]

			self._cdp_listeners_registered = True
			self.logger.info('✅ Captcha CDP event listeners registered')

		except Exception as e:
			self.logger.warning(f'⚠️ Failed to register captcha CDP event listeners: {e}')
			# Non-fatal - captcha events just won't work
