from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from cdp_use import CDPClient
from cdp_use.cdp.target import TargetID

from browser_use.browser.session import BrowserSession, Target
from browser_use.browser.session_manager import SessionManager


def _target_id(target_id: str) -> TargetID:
	return cast(TargetID, target_id)


def _target(target_id: str, target_type: str, url: str) -> Target:
	return Target(target_id=_target_id(target_id), target_type=target_type, url=url)


def test_get_all_page_targets_filters_chrome_helper_pages_but_keeps_new_tab_pages():
	session = BrowserSession()
	manager = SessionManager(session)
	manager.logger = MagicMock()
	manager._targets = {
		_target_id('normal'): _target('normal', 'page', 'https://example.com'),
		_target_id('blank'): _target('blank', 'page', 'about:blank'),
		_target_id('newtab'): _target('newtab', 'page', 'chrome://newtab/'),
		_target_id('new-tab-page'): _target('new-tab-page', 'tab', 'chrome://new-tab-page/'),
		_target_id('omnibox'): _target('omnibox', 'page', 'chrome://omnibox-popup/'),
		_target_id('settings'): _target('settings', 'tab', 'chrome://settings/'),
		_target_id('iframe'): _target('iframe', 'iframe', 'https://example.com/frame'),
	}

	page_target_ids = [str(target.target_id) for target in manager.get_all_page_targets()]

	assert page_target_ids == ['normal', 'blank', 'newtab', 'new-tab-page']


@pytest.mark.asyncio
async def test_cdp_create_new_page_can_request_new_window():
	session = BrowserSession()
	create_target = AsyncMock(return_value={'targetId': 'target-1'})
	session._cdp_client_root = cast(
		CDPClient,
		SimpleNamespace(send=SimpleNamespace(Target=SimpleNamespace(createTarget=create_target))),
	)

	target_id = await session._cdp_create_new_page('about:blank', new_window=True)

	assert target_id == 'target-1'
	create_target.assert_awaited_once()
	await_args = create_target.await_args
	assert await_args is not None
	assert await_args.kwargs['params'] == {
		'url': 'about:blank',
		'background': False,
		'newWindow': True,
	}
