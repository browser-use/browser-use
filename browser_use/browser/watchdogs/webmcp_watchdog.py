"""Watchdog for discovering and managing WebMCP tools on pages"""

from typing import TYPE_CHECKING, ClassVar

from bubus import BaseEvent
from pydantic import PrivateAttr

from browser_use.browser.events import BrowserConnectedEvent, NavigationCompleteEvent, WebMCPToolsChangedEvent
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.webmcp.service import WebMCPService

if TYPE_CHECKING:
	from browser_use.tools.registry.service import Registry


class WebMCPWatchdog(BaseWatchdog):
	"""Discovers WebMCP tools after navigation and registers them as browser-use actions

	On browser connect, injects the bridge.js script via addScriptToEvaluateOnNewDocument
	so that navigator.modelContext is available on every page. After each navigation,
	queries the bridge to discover registered tools and syncs them to the action registry.
	"""

	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [BrowserConnectedEvent, NavigationCompleteEvent]
	EMITS: ClassVar[list[type[BaseEvent]]] = [WebMCPToolsChangedEvent]

	_service: WebMCPService = PrivateAttr(default_factory=WebMCPService)
	_bridge_script_id: str | None = PrivateAttr(default=None)
	_registry: 'Registry | None' = PrivateAttr(default=None)

	def set_registry(self, registry: 'Registry') -> None:
		"""Set the tools registry for dynamic action registration."""
		self._registry = registry

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""Inject the WebMCP bridge when the browser connects."""
		try:
			bridge_js = WebMCPService.get_bridge_js()
			self._bridge_script_id = await self.browser_session._cdp_add_init_script(bridge_js)
			self.logger.debug('WebMCP bridge injected via addScriptToEvaluateOnNewDocument')
		except Exception as e:
			self.logger.debug(f'Failed to inject WebMCP bridge: {e}')

	async def on_NavigationCompleteEvent(self, event: NavigationCompleteEvent) -> None:
		"""Discover WebMCP tools after each navigation."""
		if not self._registry:
			self.logger.debug('WebMCP watchdog has no registry set, skipping discovery')
			return

		url = event.url
		if not url or not url.startswith(('http://', 'https://')):
			return

		tools = await self._service.discover_tools(self.browser_session)
		self._service.sync_actions_to_registry(self._registry, tools, url, self.browser_session)

		self.event_bus.dispatch(
			WebMCPToolsChangedEvent(
				target_id=event.target_id,
				url=url,
				tool_names=[t.name for t in tools],
			)
		)
