"""Watchdog for handling JavaScript dialogs (alert, confirm, prompt) automatically."""

import asyncio
from typing import ClassVar

from bubus import BaseEvent
from pydantic import PrivateAttr

from browser_use.browser.events import DialogOpenedEvent, TabCreatedEvent
from browser_use.browser.watchdog_base import BaseWatchdog


class PopupsWatchdog(BaseWatchdog):
	"""Handles JavaScript dialogs (alert, confirm, prompt) by automatically accepting them."""

	# Events this watchdog listens to and emits
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [TabCreatedEvent, DialogOpenedEvent]
	EMITS: ClassVar[list[type[BaseEvent]]] = [DialogOpenedEvent]

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
			cdp_session = await self.browser_session.get_or_create_cdp_session(
				target_id, focus=False
			)  # don't auto-focus new tabs! sometimes we need to open tabs in background

			# Set up async handler for JavaScript dialogs - now we can handle them immediately!
			async def handle_dialog(event_data, session_id: str | None = None):
				"""Handle JavaScript dialog events - accept immediately and dispatch event."""
				self.logger.debug(f'🚨 DIALOG EVENT RECEIVED: {event_data}, session_id={session_id}')

				dialog_type = event_data.get('type', 'alert')
				message = event_data.get('message', '')
				url = event_data.get('url')
				frame_id = event_data.get('frameId')

				self.logger.debug(f"🔔 JavaScript {dialog_type} dialog detected: '{message[:50]}...' - accepting immediately")

				# Dispatch the event first so tests can observe it
				event = self.browser_session.event_bus.dispatch(
					DialogOpenedEvent(
						frame_id=frame_id,
						dialog_type=dialog_type,
						message=message,
						url=url,
					)
				)
				await event.event_result(raise_if_none=False, raise_if_any=True, timeout=5.0)

				# Accept the dialog immediately to unblock the browser
				try:
					if self.browser_session._cdp_client_root and session_id:
						self.logger.debug('🔄 Sending handleJavaScriptDialog command')
						await self.browser_session._cdp_client_root.send.Page.handleJavaScriptDialog(
							params={'accept': True},
							session_id=session_id,
						)
						self.logger.info('✅ Dialog accepted successfully')
					else:
						self.logger.error('Cannot accept dialog - CDP client or session not available')
				except Exception as e:
					self.logger.error(f'Failed to accept dialog: {e}')

			cdp_session.cdp_client.register.Page.javascriptDialogOpening(handle_dialog)  # type: ignore[arg-type]
			self.logger.debug(
				f'Successfully registered Page.javascriptDialogOpening handler for session {cdp_session.session_id}'
			)

			# Mark this target as having dialog handling set up
			self._dialog_listeners_registered.add(target_id)

			self.logger.debug(f'Set up JavaScript dialog handling for tab {target_id}')

		except Exception as e:
			self.logger.warning(f'Failed to set up dialog handling for tab {target_id}: {e}')

	async def on_DialogOpenedEvent(self, event: DialogOpenedEvent) -> None:
		"""Handle the async closing of JavaScript dialogs."""
		self.logger.debug(
			f'📋 on_DialogOpenedEvent called with frame_id={event.frame_id} url={event.url} message={event.message}'
		)

		assert self.browser_session.agent_focus is not None, 'Agent focus not set when handling DialogOpenedEvent'

		current_focus_url = self.browser_session.agent_focus.url
		current_focus_target_id = self.browser_session.agent_focus.target_id

		cdp_session = await asyncio.wait_for(self.browser_session.cdp_client_for_frame(event.frame_id), timeout=5.0)
		try:
			# delay to look more human before auto-closing, some popular antibot fingerprint tests check for modals closing too fast
			await asyncio.sleep(0.25)
			assert self.browser_session._cdp_client_root
			# self.browser_session._cdp_client_root.register.Page.javascriptDialogClosed(lambda *args: None)
			await asyncio.wait_for(
				self.browser_session._cdp_client_root.send.Page.handleJavaScriptDialog(
					params={'accept': True},
					session_id=cdp_session.session_id,
				),
				timeout=5.0,
			)
			# CRITICAL: you must re-focus (Target.activateTarget()) after handling the dialog, otherwise the browser will crash ~5 seconds later
			await self.browser_session.get_or_create_cdp_session(target_id=current_focus_target_id, focus=True)
			self.logger.info('✅ JS dialog popup handled successfully')

			# graveyard of past attempts:
			# # new_target = await self.browser_session._cdp_client_root.send.Target.createTarget(params={'url': current_focus_url})
			# # self.browser_session.agent_focus = await self.browser_session.get_or_create_cdp_session(target_id=new_target.get('targetId'), new_socket=True, focus=True)
			# # raise NotImplementedError('TODO: figure out why this requires a hard refresh and new socket to avoid crashing the entire browser on JS dialogs')
			# await asyncio.sleep(0.2)
			# await asyncio.wait_for(
			# 	self.browser_session._cdp_client_root.send.Runtime.evaluate(
			# 		params={'expression': '1'},
			# 		session_id=cdp_session.session_id,
			# 	),
			# 	timeout=5.0,
			# )
			# # self.browser_session.agent_focus = await self.browser_session.get_or_create_cdp_session(current_focus.target_id, focus=True, new_socket=True)
			# # assert await self.browser_session.agent_focus.cdp_client.send.Page.getFrameTree(session_id=self.browser_session.agent_focus.session_id) is not None, "Agent focus not set after handling dialog"
		except Exception as e:
			self.logger.error(f'Failed to handle JavaScript dialog gracefully: {e}')
			# raise
		# finally:
		# 	self.event_bus.dispatch(AgentFocusChangedEvent(
		# 		target_id=current_focus_target_id,
		# 		url=self.browser_session.agent_focus.url,
		# 	))
