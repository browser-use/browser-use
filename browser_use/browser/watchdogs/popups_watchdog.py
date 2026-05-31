"""Compatibility wrapper for dialog setup.

Dialog handling is owned by :class:`browser_use.browser.services.DialogService`.
This watchdog remains only for old event-bus integrations that still dispatch
``TabCreatedEvent`` directly.
"""

from typing import ClassVar

from bubus import BaseEvent

from browser_use.browser.events import TabCreatedEvent
from browser_use.browser.watchdog_base import BaseWatchdog


class PopupsWatchdog(BaseWatchdog):
	"""Compatibility adapter for JavaScript dialog handling."""

	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [TabCreatedEvent]
	EMITS: ClassVar[list[type[BaseEvent]]] = []

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		await self.register_dialog_handlers(event.target_id)

	async def register_dialog_handlers(self, target_id: str) -> None:
		from browser_use.browser.services import DialogService

		await DialogService(browser_session=self.browser_session).register_handlers(target_id)
