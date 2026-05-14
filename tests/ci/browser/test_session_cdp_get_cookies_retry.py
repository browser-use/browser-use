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
		_is_connection_related_error=BrowserSession._is_connection_related_error,
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
		_is_connection_related_error=BrowserSession._is_connection_related_error,
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
		_is_connection_related_error=BrowserSession._is_connection_related_error,
		logger=MagicMock(),
	)
	fake_session._reconnect_event.set()

	with pytest.raises(ValueError, match='bad cookie format'):
		await BrowserSession._cdp_get_cookies(cast(Any, fake_session))

	fake_session.get_or_create_cdp_session.assert_awaited_once_with(target_id=None)
	storage.getCookies.assert_awaited_once_with(session_id='s1')


async def test_cdp_set_cookies_returns_early_when_no_focus_or_empty_cookie_list():
	fake_session = SimpleNamespace(
		agent_focus_target_id=None,
		get_or_create_cdp_session=AsyncMock(),
		is_reconnecting=False,
		RECONNECT_WAIT_TIMEOUT=54.0,
		_reconnect_event=asyncio.Event(),
		_is_connection_related_error=BrowserSession._is_connection_related_error,
		logger=MagicMock(),
	)
	fake_session._reconnect_event.set()

	await BrowserSession._cdp_set_cookies(cast(Any, fake_session), [])

	fake_session.get_or_create_cdp_session.assert_not_awaited()


async def test_cdp_set_cookies_retries_once_after_connection_error():
	first_storage = SimpleNamespace(setCookies=AsyncMock(side_effect=ConnectionError('WebSocket connection closed')))
	second_storage = SimpleNamespace(setCookies=AsyncMock(return_value=None))
	first_cdp = SimpleNamespace(session_id='s1', cdp_client=SimpleNamespace(send=SimpleNamespace(Storage=first_storage)))
	second_cdp = SimpleNamespace(session_id='s2', cdp_client=SimpleNamespace(send=SimpleNamespace(Storage=second_storage)))

	fake_session = SimpleNamespace(
		agent_focus_target_id='tab-1',
		get_or_create_cdp_session=AsyncMock(side_effect=[first_cdp, second_cdp]),
		is_reconnecting=True,
		RECONNECT_WAIT_TIMEOUT=54.0,
		_reconnect_event=asyncio.Event(),
		_is_connection_related_error=BrowserSession._is_connection_related_error,
		logger=MagicMock(),
	)
	fake_session._reconnect_event.set()

	await BrowserSession._cdp_set_cookies(cast(Any, fake_session), cast(Any, [{'name': 'a'}]))

	assert fake_session.get_or_create_cdp_session.await_count == 2
	first_storage.setCookies.assert_awaited_once()
	second_storage.setCookies.assert_awaited_once()


async def test_cdp_set_cookies_does_not_retry_for_non_connection_errors():
	storage = SimpleNamespace(setCookies=AsyncMock(side_effect=ValueError('invalid cookie')))
	cdp_session = SimpleNamespace(session_id='s1', cdp_client=SimpleNamespace(send=SimpleNamespace(Storage=storage)))

	fake_session = SimpleNamespace(
		agent_focus_target_id='tab-1',
		get_or_create_cdp_session=AsyncMock(return_value=cdp_session),
		is_reconnecting=False,
		RECONNECT_WAIT_TIMEOUT=54.0,
		_reconnect_event=asyncio.Event(),
		_is_connection_related_error=BrowserSession._is_connection_related_error,
		logger=MagicMock(),
	)
	fake_session._reconnect_event.set()

	with pytest.raises(ValueError, match='invalid cookie'):
		await BrowserSession._cdp_set_cookies(cast(Any, fake_session), cast(Any, [{'name': 'a'}]))

	fake_session.get_or_create_cdp_session.assert_awaited_once_with(target_id=None)
	storage.setCookies.assert_awaited_once()
