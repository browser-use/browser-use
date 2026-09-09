from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from browser_use.browser import BrowserSession
from browser_use.browser.events import GoBackEvent
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
from browser_use.mcp.server import BrowserUseServer
from browser_use.tools.service import Tools


class CompletedGoBackEvent:
	def __init__(self, did_navigate: bool):
		self.did_navigate = did_navigate

	async def event_result(self, **kwargs):
		return self.did_navigate


async def test_go_back_handler_reports_no_history():
	cdp_session = MagicMock()
	cdp_session.cdp_client.send.Page.getNavigationHistory = AsyncMock(return_value={'currentIndex': 0, 'entries': []})
	browser_session = MagicMock(spec=BrowserSession)
	browser_session.get_or_create_cdp_session = AsyncMock(return_value=cdp_session)

	watchdog = DefaultActionWatchdog.model_construct(event_bus=MagicMock(), browser_session=browser_session)

	assert await watchdog.on_GoBackEvent(GoBackEvent()) is False


async def test_go_back_tool_returns_error_when_history_is_empty():
	event = CompletedGoBackEvent(did_navigate=False)
	browser_session = SimpleNamespace(cdp_client=None, event_bus=SimpleNamespace(dispatch=lambda _: event))

	result = await Tools().go_back(browser_session=browser_session)

	assert result.error == 'Cannot go back - no previous entry in history'
	assert result.extracted_content is None


async def test_go_back_mcp_returns_error_when_history_is_empty():
	event = CompletedGoBackEvent(did_navigate=False)
	server = cast(
		BrowserUseServer,
		SimpleNamespace(browser_session=SimpleNamespace(event_bus=SimpleNamespace(dispatch=lambda _: event))),
	)

	result = await BrowserUseServer._go_back(server)

	assert result == 'Error: Cannot go back - no previous entry in history'
