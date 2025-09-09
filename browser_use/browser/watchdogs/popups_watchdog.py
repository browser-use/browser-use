"""Watchdog for handling JavaScript dialogs (alert, confirm, prompt) automatically."""

import asyncio
from typing import ClassVar

from bubus import BaseEvent
from pydantic import PrivateAttr

from browser_use.browser.events import TabCreatedEvent
from browser_use.browser.watchdog_base import BaseWatchdog


class PopupsWatchdog(BaseWatchdog):
	"""Handles JavaScript dialogs (alert, confirm, prompt) by automatically accepting them immediately."""

	# Events this watchdog listens to and emits
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [TabCreatedEvent]
	EMITS: ClassVar[list[type[BaseEvent]]] = []

	# Track which targets have dialog handlers registered
	_dialog_listeners_registered: set[str] = PrivateAttr(default_factory=set)

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.logger.debug(f'🚀 PopupsWatchdog initialized with browser_session={self.browser_session}, ID={id(self)}')

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Set up JavaScript dialog handling when a new tab is created."""
		target_id = event.target_id
		self.logger.debug(f'🎯 PopupsWatchdog received TabCreatedEvent for target {target_id}')

		# Skip if we've already registered for this target
		if target_id in self._dialog_listeners_registered:
			self.logger.debug(f'Already registered dialog handlers for target {target_id}')
			return

		self.logger.debug(f'📌 Starting dialog handler setup for target {target_id}')
		try:
			# Get all CDP sessions for this target and any child frames
			cdp_session = await self.browser_session.get_or_create_cdp_session(
				target_id, focus=False
			)  # don't auto-focus new tabs! sometimes we need to open tabs in background

			# Also register for the root CDP client to catch dialogs from any frame
			if self.browser_session._cdp_client_root:
				self.logger.debug('📌 Also registering handler on root CDP client')

			# Set up async handler for JavaScript dialogs - accept immediately without event dispatch
			async def handle_dialog(event_data, session_id: str | None = None):
				"""Handle JavaScript dialog events - accept immediately."""
				try:
					dialog_type = event_data.get('type', 'alert')
					message = event_data.get('message', '')

					self.logger.info(f"🔔 JavaScript {dialog_type} dialog: '{message[:100]}' - attempting to accept...")

					self.logger.debug('Trying all approaches to accept dialog...')

					# Approach 1: Use the session that detected the dialog
					if self.browser_session._cdp_client_root and session_id:
						try:
							self.logger.debug(f'🔄 Approach 1: Using session {session_id}')
							await asyncio.wait_for(
								self.browser_session._cdp_client_root.send.Page.handleJavaScriptDialog(
									params={'accept': True},
									session_id=session_id,
								),
								timeout=0.25,
							)
						except (TimeoutError, Exception) as e:
							pass

					# Approach 2: Try with current agent focus session
					if self.browser_session._cdp_client_root and self.browser_session.agent_focus:
						try:
							self.logger.debug(
								f'🔄 Approach 2: Using agent focus session {self.browser_session.agent_focus.session_id}'
							)
							await asyncio.wait_for(
								self.browser_session._cdp_client_root.send.Page.handleJavaScriptDialog(
									params={'accept': True},
									session_id=self.browser_session.agent_focus.session_id,
								),
								timeout=0.25,
							)
						except (TimeoutError, Exception) as e:
							pass

				except Exception as e:
					self.logger.error(f'❌ Critical error in dialog handler: {type(e).__name__}: {e}')

			# Register handler on the specific session
			cdp_session.cdp_client.register.Page.javascriptDialogOpening(handle_dialog)  # type: ignore[arg-type]
			self.logger.debug(
				f'Successfully registered Page.javascriptDialogOpening handler for session {cdp_session.session_id}'
			)

			# Also register on root CDP client to catch dialogs from any frame
			if hasattr(self.browser_session._cdp_client_root, 'register'):
				try:
					self.browser_session._cdp_client_root.register.Page.javascriptDialogOpening(handle_dialog)  # type: ignore[arg-type]
					self.logger.debug('Successfully registered dialog handler on root CDP client for all frames')
				except Exception as root_error:
					self.logger.warning(f'Failed to register on root CDP client: {root_error}')

			# Mark this target as having dialog handling set up
			self._dialog_listeners_registered.add(target_id)

			self.logger.debug(f'Set up JavaScript dialog handling for tab {target_id}')

		except Exception as e:
			self.logger.warning(f'Failed to set up popup handling for tab {target_id}: {e}')
