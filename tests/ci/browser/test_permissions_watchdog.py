from unittest.mock import AsyncMock

import pytest

from browser_use.browser.events import BrowserConnectedEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.permissions_watchdog import PermissionsWatchdog


class _StubBrowserSend:
	def __init__(self) -> None:
		self.calls: list[dict] = []

	async def grantPermissions(self, params: dict, session_id: str | None = None) -> None:
		self.calls.append({'params': params, 'session_id': session_id})


class _StubSend:
	def __init__(self) -> None:
		self.Browser = _StubBrowserSend()


class _StubCDPClient:
	def __init__(self) -> None:
		self.send = _StubSend()


@pytest.mark.asyncio
async def test_cdp_grant_permissions_forwards_origin_to_browser_domain():
	session = BrowserSession()
	session._cdp_client_root = _StubCDPClient()  # type: ignore[assignment]

	await session._cdp_grant_permissions(['clipboardReadWrite', 'notifications'], origin='https://example.com')

	calls = session._cdp_client_root.send.Browser.calls  # type: ignore[union-attr]
	assert calls == [
		{
			'params': {
				'permissions': ['clipboardReadWrite', 'notifications'],
				'origin': 'https://example.com',
			},
			'session_id': None,
		}
	]


@pytest.mark.asyncio
async def test_permissions_watchdog_uses_browser_session_helper():
	session = BrowserSession(browser_profile=BrowserProfile(permissions=['notifications']))
	session._cdp_grant_permissions = AsyncMock()  # type: ignore[method-assign]
	watchdog = PermissionsWatchdog(event_bus=session.event_bus, browser_session=session)

	await watchdog.on_BrowserConnectedEvent(BrowserConnectedEvent(cdp_url='ws://example.test/devtools/browser/abc'))

	session._cdp_grant_permissions.assert_awaited_once_with(['notifications'], origin=None)
