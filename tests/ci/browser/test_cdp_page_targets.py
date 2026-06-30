from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.browser.session import BrowserSession
from browser_use.browser.session_manager import SessionManager


def _target(target_id: str, target_type: str, url: str):
	return SimpleNamespace(target_id=target_id, target_type=target_type, url=url)


def test_get_all_page_targets_filters_chrome_helper_pages_but_keeps_new_tab_pages():
	manager = SessionManager(SimpleNamespace(logger=MagicMock()))
	manager._targets = {
		'normal': _target('normal', 'page', 'https://example.com'),
		'blank': _target('blank', 'page', 'about:blank'),
		'newtab': _target('newtab', 'page', 'chrome://newtab/'),
		'new-tab-page': _target('new-tab-page', 'tab', 'chrome://new-tab-page/'),
		'omnibox': _target('omnibox', 'page', 'chrome://omnibox-popup/'),
		'settings': _target('settings', 'tab', 'chrome://settings/'),
		'iframe': _target('iframe', 'iframe', 'https://example.com/frame'),
	}

	page_target_ids = [target.target_id for target in manager.get_all_page_targets()]

	assert page_target_ids == ['normal', 'blank', 'newtab', 'new-tab-page']


@pytest.mark.asyncio
async def test_cdp_create_new_page_can_request_new_window():
	session = BrowserSession()
	create_target = AsyncMock(return_value={'targetId': 'target-1'})
	session._cdp_client_root = SimpleNamespace(
		send=SimpleNamespace(Target=SimpleNamespace(createTarget=create_target)),
	)

	target_id = await session._cdp_create_new_page('about:blank', new_window=True)

	assert target_id == 'target-1'
	create_target.assert_awaited_once()
	assert create_target.await_args.kwargs['params'] == {
		'url': 'about:blank',
		'background': False,
		'newWindow': True,
	}
