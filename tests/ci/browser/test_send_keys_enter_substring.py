"""Regression: Enter post-send delay must not fire on ordinary text substrings."""

import asyncio
from types import SimpleNamespace

import pytest

from browser_use.browser.events import SendKeysEvent
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog


def _make_watchdog():
	class Input:
		async def dispatchKeyEvent(self, params=None, session_id=None):
			return None

	cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(send=SimpleNamespace(Input=Input())),
		session_id='session-1',
	)

	class BrowserSession:
		async def get_or_create_cdp_session(self, focus=False):
			return cdp_session

	async def dispatch_key_event(_session, event_type, key, modifiers=0):
		return None

	return SimpleNamespace(
		browser_session=BrowserSession(),
		logger=SimpleNamespace(info=lambda *args, **kwargs: None),
		_dispatch_key_event=dispatch_key_event,
		_get_char_modifiers_and_vk=lambda char: (0, 0, char),
		_get_key_code_for_char=lambda key: f'Key{key.upper()}',
	)


@pytest.mark.parametrize(
	'keys,expect_enter_delay',
	[
		('Enter', True),
		('Return', True),
		('ENTER', True),
		('Control+Enter', True),
		('center', False),
		('returning', False),
		('hello', False),
		('enterprise', False),
	],
)
def test_send_keys_enter_delay_only_for_real_enter(keys, expect_enter_delay, monkeypatch):
	delays: list[float] = []

	async def sleep(delay):
		delays.append(delay)

	monkeypatch.setattr(asyncio, 'sleep', sleep)

	watchdog = _make_watchdog()
	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys=keys)))

	enter_delays = [delay for delay in delays if delay == 0.1]
	if expect_enter_delay:
		assert enter_delays == [0.1], f'{keys!r} should request the Enter delay'
	else:
		assert enter_delays == [], f'{keys!r} should not request the Enter delay'
