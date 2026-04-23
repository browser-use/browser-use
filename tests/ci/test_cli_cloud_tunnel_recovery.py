from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from browser_use.skill_cli.actions import ActionHandler


async def test_navigate_does_not_retry_when_navigation_succeeds():
	bs = SimpleNamespace(
		agent_focus_target_id='tab-1',
		browser_profile=SimpleNamespace(use_cloud=True, cdp_url='wss://cloud.example/devtools/browser/old'),
		_navigate_and_wait=AsyncMock(return_value=None),
		stop=AsyncMock(),
		start=AsyncMock(),
	)
	handler = ActionHandler.__new__(ActionHandler)
	cast(Any, handler).bs = bs

	await handler.navigate('https://example.com')

	bs._navigate_and_wait.assert_awaited_once_with('https://example.com', 'tab-1')
	bs.stop.assert_not_awaited()
	bs.start.assert_not_awaited()


async def test_navigate_retries_once_after_cloud_tunnel_failure():
	async def _restart_session():
		assert bs.browser_profile.cdp_url is None
		bs.browser_profile.cdp_url = 'wss://cloud.example/devtools/browser/new'
		bs.agent_focus_target_id = 'tab-2'

	bs = SimpleNamespace(
		agent_focus_target_id='tab-1',
		browser_profile=SimpleNamespace(use_cloud=True, cdp_url='wss://cloud.example/devtools/browser/old'),
		_navigate_and_wait=AsyncMock(
			side_effect=[
				RuntimeError('Navigation failed: net::ERR_TUNNEL_CONNECTION_FAILED'),
				None,
			]
		),
		stop=AsyncMock(),
		start=AsyncMock(side_effect=_restart_session),
	)
	handler = ActionHandler.__new__(ActionHandler)
	cast(Any, handler).bs = bs

	await handler.navigate('https://example.com')

	assert bs._navigate_and_wait.await_count == 2
	first_call = bs._navigate_and_wait.await_args_list[0]
	second_call = bs._navigate_and_wait.await_args_list[1]
	assert first_call.args == ('https://example.com', 'tab-1')
	assert second_call.args == ('https://example.com', 'tab-2')
	bs.stop.assert_awaited_once()
	bs.start.assert_awaited_once()
	assert bs.browser_profile.cdp_url == 'wss://cloud.example/devtools/browser/new'


async def test_navigate_does_not_retry_tunnel_failure_for_local_browser():
	bs = SimpleNamespace(
		agent_focus_target_id='tab-1',
		browser_profile=SimpleNamespace(use_cloud=False, cdp_url='http://localhost:9222'),
		_navigate_and_wait=AsyncMock(side_effect=RuntimeError('Navigation failed: net::ERR_TUNNEL_CONNECTION_FAILED')),
		stop=AsyncMock(),
		start=AsyncMock(),
	)
	handler = ActionHandler.__new__(ActionHandler)
	cast(Any, handler).bs = bs

	with pytest.raises(RuntimeError, match='ERR_TUNNEL_CONNECTION_FAILED'):
		await handler.navigate('https://example.com')

	bs._navigate_and_wait.assert_awaited_once_with('https://example.com', 'tab-1')
	bs.stop.assert_not_awaited()
	bs.start.assert_not_awaited()
	assert bs.browser_profile.cdp_url == 'http://localhost:9222'
