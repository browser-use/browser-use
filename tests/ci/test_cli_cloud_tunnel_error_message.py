from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from browser_use.skill_cli.commands.browser import handle


async def test_open_raises_cloud_tunnel_guidance_after_retry_failure():
	actions = SimpleNamespace(
		navigate=AsyncMock(side_effect=RuntimeError('Navigation failed: net::ERR_TUNNEL_CONNECTION_FAILED'))
	)
	browser_session = SimpleNamespace(browser_profile=SimpleNamespace(use_cloud=True), cdp_url='wss://cloud.example/devtools')
	session = SimpleNamespace(browser_session=browser_session, actions=actions)

	with pytest.raises(RuntimeError, match='ERR_TUNNEL_CONNECTION_FAILED after retry'):
		await handle('open', cast(Any, session), {'url': 'https://example.com'})

	actions.navigate.assert_awaited_once_with('https://example.com')


async def test_open_keeps_original_error_for_non_cloud_sessions():
	actions = SimpleNamespace(
		navigate=AsyncMock(side_effect=RuntimeError('Navigation failed: net::ERR_TUNNEL_CONNECTION_FAILED'))
	)
	browser_session = SimpleNamespace(browser_profile=SimpleNamespace(use_cloud=False), cdp_url=None)
	session = SimpleNamespace(browser_session=browser_session, actions=actions)

	with pytest.raises(RuntimeError, match='Navigation failed: net::ERR_TUNNEL_CONNECTION_FAILED'):
		await handle('open', cast(Any, session), {'url': 'https://example.com'})

	actions.navigate.assert_awaited_once_with('https://example.com')
