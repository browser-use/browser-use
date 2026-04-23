import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.browser.session import BrowserSession


async def test_cdp_get_cookies_returns_cookies_without_retry():
	storage = SimpleNamespace(getCookies=AsyncMock(return_value={'cookies': [{'name': 'a'}]}))
	send = SimpleNamespace(Storage=storage)
	cdp_session = SimpleNamespace(session_id='s1', cdp_client=SimpleNamespace(send=send))

	fake_session = SimpleNamespace(
		get_or_create_cdp_session=AsyncMock(return_value=cdp_session),
		is_reconnecting=False,
		RECONNECT_WAIT_TIMEOUT=54.0,
		_reconnect_event=asyncio.Event(),
		logger=MagicMock(),
	)
	fake_session._reconnect_event.set()

	cookies = await BrowserSession._cdp_get_cookies(cast(Any, fake_session))

	assert cookies == [{'name': 'a'}]
	fake_session.get_or_create_cdp_session.assert_awaited_once_with(target_id=None)
	storage.getCookies.assert_awaited_once_with(session_id='s1')


async def test_cdp_get_cookies_retries_once_after_connection_error():
	first_storage = SimpleNamespace(getCookies=AsyncMock(side_effect=ConnectionError('WebSocket connection closed')))
	second_storage = SimpleNamespace(getCookies=AsyncMock(return_value={'cookies': [{'name': 'b'}]}))
	first_cdp = SimpleNamespace(session_id='s1', cdp_client=SimpleNamespace(send=SimpleNamespace(Storage=first_storage)))
	second_cdp = SimpleNamespace(session_id='s2', cdp_client=SimpleNamespace(send=SimpleNamespace(Storage=second_storage)))

	fake_session = SimpleNamespace(
		get_or_create_cdp_session=AsyncMock(side_effect=[first_cdp, second_cdp]),
		is_reconnecting=True,
		RECONNECT_WAIT_TIMEOUT=54.0,
		_reconnect_event=asyncio.Event(),
		logger=MagicMock(),
	)
	fake_session._reconnect_event.set()

	cookies = await BrowserSession._cdp_get_cookies(cast(Any, fake_session))

	assert cookies == [{'name': 'b'}]
	assert fake_session.get_or_create_cdp_session.await_count == 2
	first_storage.getCookies.assert_awaited_once_with(session_id='s1')
	second_storage.getCookies.assert_awaited_once_with(session_id='s2')


async def test_cdp_get_cookies_does_not_retry_for_non_connection_errors():
	storage = SimpleNamespace(getCookies=AsyncMock(side_effect=ValueError('bad cookie format')))
	cdp_session = SimpleNamespace(session_id='s1', cdp_client=SimpleNamespace(send=SimpleNamespace(Storage=storage)))

	fake_session = SimpleNamespace(
		get_or_create_cdp_session=AsyncMock(return_value=cdp_session),
		is_reconnecting=False,
		RECONNECT_WAIT_TIMEOUT=54.0,
		_reconnect_event=asyncio.Event(),
		logger=MagicMock(),
	)
	fake_session._reconnect_event.set()

	with pytest.raises(ValueError, match='bad cookie format'):
		await BrowserSession._cdp_get_cookies(cast(Any, fake_session))

	fake_session.get_or_create_cdp_session.assert_awaited_once_with(target_id=None)
	storage.getCookies.assert_awaited_once_with(session_id='s1')
