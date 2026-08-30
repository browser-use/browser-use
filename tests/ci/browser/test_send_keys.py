import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.browser.events import SendKeysEvent
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog


@pytest.mark.parametrize(
	('keys', 'expects_enter_delay'),
	[
		('Enter', True),
		('Return', True),
		('ENTER', True),
		('ctrl+enter', True),
		('line\nbreak', True),
		('center', False),
		('returning', False),
	],
)
async def test_send_keys_enter_delay_matches_dispatched_key(monkeypatch, keys, expects_enter_delay):
	delays = []

	async def record_sleep(delay):
		delays.append(delay)

	monkeypatch.setattr(asyncio, 'sleep', record_sleep)
	cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(send=SimpleNamespace(Input=SimpleNamespace(dispatchKeyEvent=AsyncMock()))),
		session_id='session-1',
	)
	watchdog = SimpleNamespace(
		browser_session=SimpleNamespace(get_or_create_cdp_session=AsyncMock(return_value=cdp_session)),
		logger=MagicMock(),
		_dispatch_key_event=AsyncMock(),
		_get_char_modifiers_and_vk=lambda char: (0, 0, char),
		_get_key_code_for_char=lambda key: f'Key{key.upper()}',
	)

	await DefaultActionWatchdog.on_SendKeysEvent(cast(DefaultActionWatchdog, watchdog), SendKeysEvent(keys=keys))

	assert (0.1 in delays) is expects_enter_delay
