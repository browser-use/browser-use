from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from browser_use.skill_cli.browser import CLIBrowserSession


async def test_cli_stop_clears_cloud_cdp_url():
	stop_browser = AsyncMock()
	session = CLIBrowserSession.model_construct()
	cast(Any, session)._intentional_stop = False
	cast(Any, session).browser_profile = SimpleNamespace(
		use_cloud=True,
		cdp_url='wss://cloud.example/devtools/browser/old',
	)
	cast(Any, session)._cloud_browser_client = SimpleNamespace(current_session_id='session-1', stop_browser=stop_browser)
	cast(Any, session)._cdp_client_root = None
	cast(Any, session).session_manager = None
	cast(Any, session).agent_focus_target_id = 'tab-1'
	cast(Any, session)._cached_selector_map = {}

	await session.stop()

	stop_browser.assert_awaited_once()
	assert cast(Any, session).browser_profile.cdp_url is None


async def test_cli_stop_keeps_non_cloud_cdp_url():
	stop_browser = AsyncMock()
	session = CLIBrowserSession.model_construct()
	cast(Any, session)._intentional_stop = False
	cast(Any, session).browser_profile = SimpleNamespace(use_cloud=False, cdp_url='http://localhost:9222')
	cast(Any, session)._cloud_browser_client = SimpleNamespace(current_session_id='session-1', stop_browser=stop_browser)
	cast(Any, session)._cdp_client_root = None
	cast(Any, session).session_manager = None
	cast(Any, session).agent_focus_target_id = 'tab-1'
	cast(Any, session)._cached_selector_map = {}

	await session.stop()

	stop_browser.assert_not_awaited()
	assert cast(Any, session).browser_profile.cdp_url == 'http://localhost:9222'
