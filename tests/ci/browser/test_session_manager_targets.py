from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.browser.events import SwitchTabEvent
from browser_use.browser.session import BrowserSession
from browser_use.browser.session_manager import SessionManager


def _target(target_id: str, target_type: str, url: str):
	return SimpleNamespace(target_id=target_id, target_type=target_type, url=url)


def test_get_all_page_targets_filters_chrome_internal_helpers():
	manager = SessionManager.__new__(SessionManager)
	manager._targets = {
		'page': _target('page', 'page', 'https://example.com'),
		'blank': _target('blank', 'page', 'about:blank'),
		'newtab': _target('newtab', 'page', 'chrome://newtab'),
		'new-tab-page': _target('new-tab-page', 'tab', 'chrome://new-tab-page/'),
		'omnibox-popup': _target('omnibox-popup', 'page', 'chrome://omnibox-popup'),
		'settings': _target('settings', 'tab', 'chrome://settings'),
		'worker': _target('worker', 'service_worker', 'https://example.com/worker.js'),
	}

	assert [target.target_id for target in manager.get_all_page_targets()] == [
		'page',
		'blank',
		'newtab',
		'new-tab-page',
	]


@pytest.mark.asyncio
async def test_switch_tab_creates_new_window_when_no_targets():
	session = BrowserSession()
	session.agent_focus_target_id = 'existing-focus'
	session.session_manager = MagicMock()
	session.session_manager.get_all_page_targets.return_value = []

	with (
		patch.object(BrowserSession, '_cdp_create_new_page', new=AsyncMock(return_value='new-target')) as create_new_page,
		patch.object(session.event_bus, 'dispatch') as dispatch,
	):
		target_id = await session.on_SwitchTabEvent(SwitchTabEvent(target_id=None))

	assert target_id == 'new-target'
	create_new_page.assert_awaited_once_with(new_window=True)
	assert dispatch.call_count == 2
