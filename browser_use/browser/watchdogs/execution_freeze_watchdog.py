"""Execution freeze watchdog — freezes JavaScript between agent steps using CDP Debugger.

- After each action settles, JS is paused via Debugger.pause
- The agent captures DOM/screenshot from a frozen, stable page
- Before the next action, JS is resumed via Debugger.resume
- Three-phase settle detection: min-wait → network tracking → post-settle
"""

import asyncio
import logging
import time
from typing import Any, ClassVar

from pydantic import PrivateAttr

from browser_use.browser.watchdog_base import BaseWatchdog

logger = logging.getLogger(__name__)

# Settle timing constants
SETTLE_MIN_WAIT_S = 0.15  # Phase 1: 150ms for JS event handlers to fire
SETTLE_NETWORK_TIMEOUT_S = 1.0  # Phase 2: 1s for same-site network requests
SETTLE_POST_WAIT_S = 0.35  # Phase 3: 350ms for DOM reflows after network settles
PAUSE_CONFIRMATION_TIMEOUT_S = 2.0  # Max wait for Debugger.paused event


class ExecutionFreezeWatchdog(BaseWatchdog):
	"""Freezes JavaScript execution between agent steps using CDP Debugger + settle detection.

	When enabled, after every action the page settles and then JS is paused.
	The agent reads frozen DOM/screenshot. Before the next action, JS is resumed.
	"""

	LISTENS_TO: ClassVar = []
	EMITS: ClassVar = []

	_is_frozen: bool = PrivateAttr(default=False)
	_paused_event: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
	_debugger_enabled_for_session: str | None = PrivateAttr(default=None)

	@property
	def is_frozen(self) -> bool:
		return self._is_frozen

	async def freeze(self) -> None:
		"""Freeze JS execution on the current page via CDP Debugger.pause.

		1. Debugger.enable (idempotent)
		2. Debugger.pause
		3. Runtime.evaluate("void 0") — forces V8 to hit the pending pause flag
		4. Wait for Debugger.paused event
		"""
		if self._is_frozen:
			return

		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session(
				target_id=self.browser_session.agent_focus_target_id, focus=True
			)
			session_id = cdp_session.session_id
			cdp_client = cdp_session.cdp_client

			# Check if page is a meaningful website (skip for about:blank, chrome://, etc.)
			url = await self.browser_session.get_current_page_url()
			if url and url.lower().split(':', 1)[0] not in ('http', 'https'):
				self.logger.debug('⏸️ Skipping freeze for non-http page')
				return

			# 1. Enable debugger if not already enabled for this session
			if self._debugger_enabled_for_session != session_id:
				await cdp_client.send.Debugger.enable(session_id=session_id)
				# Register paused event callback
				cdp_client.register.Debugger.paused(self._on_debugger_paused)  # type: ignore[arg-type]
				self._debugger_enabled_for_session = session_id

			# 2. Request pause
			self._paused_event.clear()
			await cdp_client.send.Debugger.pause(session_id=session_id)

			# 3. Force V8 to execute a statement and hit the pending pause flag.
			# Must NOT include disableBreaks — that's the whole point.
			try:
				await cdp_client.send.Runtime.evaluate(
					params={'expression': 'void 0'},
					session_id=session_id,
				)
			except Exception:
				# Runtime.evaluate may fail if the page has no JS context (e.g. static HTML).
				# The pause may still take effect — proceed to wait for the event.
				pass

			# 4. Wait for Debugger.paused event
			try:
				await asyncio.wait_for(self._paused_event.wait(), timeout=PAUSE_CONFIRMATION_TIMEOUT_S)
				self._is_frozen = True
				self.logger.debug('⏸️ Page frozen (JS execution paused)')
			except asyncio.TimeoutError:
				# Page might have no JS at all — that's fine, it's effectively frozen
				self._is_frozen = True
				self.logger.debug('⏸️ Debugger.paused timeout — page may have no JS, treating as frozen')

		except Exception as e:
			self.logger.warning(f'⏸️ Failed to freeze page: {e}')
			# Don't set _is_frozen — degrade gracefully

	async def unfreeze(self) -> None:
		"""Resume JS execution before dispatching the next action.

		Uses disableOnResume=True to prevent anti-debugging `debugger;` statements
		from re-entering the pause
		"""
		if not self._is_frozen:
			return

		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session(
				target_id=self.browser_session.agent_focus_target_id, focus=True
			)
			session_id = cdp_session.session_id
			cdp_client = cdp_session.cdp_client

			# Debugger.resume with disableOnResume — bypasses typed interface since
			# cdp-use's ResumeParameters only has terminateOnResume, not disableOnResume.
			await cdp_client.send_raw(
				method='Debugger.resume',
				params={'disableOnResume': True},
				session_id=session_id,
			)

			self._is_frozen = False
			self.logger.debug('▶️ Page unfrozen (JS execution resumed)')

		except Exception as e:
			self.logger.warning(f'▶️ Failed to unfreeze page: {e}')
			self._is_frozen = False  # Assume unfrozen on error

	async def settle_and_freeze(self) -> None:
		"""Three-phase settle detection then freeze. Called after action execution.

		Phase 1: 150ms min-wait — gives JS event handlers time to fire and initiate requests.
		Phase 2: Track pending network requests, 1s timeout.
		Phase 3: 350ms post-settle — DOM reflows, paint, JS callbacks from completed XHRs.
		Then freeze.
		"""
		try:
			# Phase 1: min-wait for JS handlers
			await asyncio.sleep(SETTLE_MIN_WAIT_S)

			# Phase 2: wait for pending network requests to complete
			start = time.monotonic()
			while time.monotonic() - start < SETTLE_NETWORK_TIMEOUT_S:
				try:
					pending = await self.browser_session._dom_watchdog._get_pending_network_requests()
					if not pending:
						break
				except Exception:
					break
				await asyncio.sleep(0.05)

			# Phase 3: post-settle wait for DOM reflows
			await asyncio.sleep(SETTLE_POST_WAIT_S)

		except Exception as e:
			self.logger.debug(f'⏸️ Settle detection error (non-fatal): {e}')

		# Freeze regardless of settle outcome
		await self.freeze()

	def on_session_changed(self) -> None:
		"""Called when the CDP session changes (e.g., cross-origin navigation).

		Resets freeze state since the old session is gone.
		"""
		self._is_frozen = False
		self._debugger_enabled_for_session = None
		self._paused_event.clear()

	def _on_debugger_paused(self, event: dict[str, Any], session_id: str | None = None) -> None:
		"""CDP event callback for Debugger.paused."""
		self._paused_event.set()
