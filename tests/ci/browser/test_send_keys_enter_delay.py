"""Tests for send_keys Enter-specific delay not applying to ordinary text."""

import asyncio
from types import SimpleNamespace

import pytest

from browser_use.browser.events import SendKeysEvent
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog


def _make_watchdog(monkeypatch):
	"""Create a minimal watchdog instance for testing send_keys delay behavior."""
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

	watchdog = SimpleNamespace(
		browser_session=BrowserSession(),
		logger=SimpleNamespace(info=lambda *args, **kwargs: None),
		_dispatch_key_event=dispatch_key_event,
		_get_char_modifiers_and_vk=lambda char: (0, 0, char),
		_get_key_code_for_char=lambda key: f'Key{key.upper()}',
	)

	return watchdog, delays


@pytest.mark.parametrize(
	'keys',
	[
		'center',
		'enterprise',
		'returning',
		'enter the building',
	],
)
def test_text_containing_enter_substring_has_no_enter_delay(monkeypatch, keys):
	"""Ordinary text containing 'enter' or 'return' should not trigger the Enter delay."""
	watchdog, delays = _make_watchdog(monkeypatch)

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys=keys)))

	enter_delays = [d for d in delays if d == 0.1]
	assert enter_delays == [], f'Unexpected Enter delay for text: {keys!r}'


def test_explicit_enter_key_has_enter_delay(monkeypatch):
	"""The explicit Enter key should trigger the 0.1s delay."""
	watchdog, delays = _make_watchdog(monkeypatch)

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys='Enter')))

	enter_delays = [d for d in delays if d == 0.1]
	assert len(enter_delays) == 1, 'Enter key should trigger exactly one 0.1s delay'


def test_ctrl_enter_combination_has_enter_delay(monkeypatch):
	"""Ctrl+Enter should trigger the Enter delay since Enter is the main key."""
	watchdog, delays = _make_watchdog(monkeypatch)

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys='Control+Enter')))

	enter_delays = [d for d in delays if d == 0.1]
	assert len(enter_delays) == 1, 'Ctrl+Enter should trigger exactly one 0.1s delay'
