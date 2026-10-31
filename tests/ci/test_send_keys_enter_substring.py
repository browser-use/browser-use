"""Regression test: the Enter-specific post-send delay must depend on the key actually sent.

`on_SendKeysEvent` used substring matching (`'enter' in event.keys.lower()`), so ordinary text such as
`center`, `enterprise` or `returning` triggered the extra 100 ms navigation wait.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from browser_use.browser.events import SendKeysEvent
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog

ENTER_DELAY = 0.1


def _watchdog(monkeypatch) -> tuple[Any, list[float]]:
	delays = []

	async def sleep(delay):
		delays.append(delay)

	monkeypatch.setattr(asyncio, 'sleep', sleep)

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
	), delays


async def _run(monkeypatch, keys: str) -> list[float]:
	watchdog: Any
	watchdog, delays = _watchdog(monkeypatch)
	await DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys=keys))
	return [delay for delay in delays if delay == ENTER_DELAY]


@pytest.mark.parametrize('keys', ['Enter', 'ENTER', 'Return', 'Control+Enter'])
async def test_enter_keys_still_wait(monkeypatch, keys: str) -> None:
	assert await _run(monkeypatch, keys) == [ENTER_DELAY]


@pytest.mark.parametrize('keys', ['center', 'enterprise', 'returning', 'hello'])
async def test_text_containing_enter_letters_does_not_wait(monkeypatch, keys: str) -> None:
	assert await _run(monkeypatch, keys) == []
