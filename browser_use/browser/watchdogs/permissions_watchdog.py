"""Permissions watchdog for granting browser permissions on connection."""

from typing import TYPE_CHECKING, ClassVar

from bubus import BaseEvent

from browser_use.browser.events import BrowserConnectedEvent
from browser_use.browser.watchdog_base import BaseWatchdog

if TYPE_CHECKING:
	pass


class PermissionsWatchdog(BaseWatchdog):
	"""Grants browser permissions when browser connects."""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		BrowserConnectedEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent]]] = []

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""Grant permissions when browser connects."""
		permissions = self.browser_session.browser_profile.permissions

		if not permissions:
			self.logger.debug('No permissions to grant')
			return

		self.logger.debug(f'🔓 Granting browser permissions: {permissions}')

		try:
			await self.browser_session._cdp_grant_permissions(permissions, origin=None)
			self.logger.debug(f'✅ Successfully granted permissions: {permissions}')
		except Exception as e:
			self.logger.error(f'❌ Failed to grant permissions: {str(e)}')
			# Don't raise - permissions are not critical to browser operation
