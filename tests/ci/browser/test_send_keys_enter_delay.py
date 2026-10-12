import asyncio
from types import SimpleNamespace
from typing import cast

import pytest

from browser_use.browser.events import SendKeysEvent
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog

ENTER_DELAY = 0.1
CHAR_DELAY = 0.010


def make_watchdog(recorded_params, dispatched_keys) -> DefaultActionWatchdog:
	class Input:
		async def dispatchKeyEvent(self, params=None, session_id=None):
			recorded_params.append(params or {})

	cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(send=SimpleNamespace(Input=Input())),
		session_id='session-1',
	)

	class BrowserSession:
		async def get_or_create_cdp_session(self, focus=False):
			return cdp_session

	async def dispatch_key_event(_session, event_type, key, modifiers=0):
		dispatched_keys.append((event_type, key, modifiers))

	watchdog = SimpleNamespace(
		browser_session=BrowserSession(),
		logger=SimpleNamespace(info=lambda *args, **kwargs: None),
		_dispatch_key_event=dispatch_key_event,
	)
	watchdog._get_char_modifiers_and_vk = DefaultActionWatchdog._get_char_modifiers_and_vk.__get__(watchdog)
	watchdog._get_key_code_for_char = DefaultActionWatchdog._get_key_code_for_char.__get__(watchdog)
	return cast(DefaultActionWatchdog, watchdog)


def send_keys_and_collect_delays(keys: str, monkeypatch: pytest.MonkeyPatch) -> list[float]:
	"""Run on_SendKeysEvent with asyncio.sleep stubbed out and return every requested delay."""
	delays: list[float] = []

	async def fake_sleep(delay, *args, **kwargs):
		delays.append(delay)

	monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

	recorded_params: list[dict] = []
	dispatched_keys: list[tuple] = []
	watchdog = make_watchdog(recorded_params, dispatched_keys)
	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys=keys)))
	return delays


@pytest.mark.parametrize('keys', ['center', 'enterprise', 'returning'])
def test_plain_text_containing_enter_or_return_gets_no_navigation_delay(monkeypatch, keys):
	"""'enter'/'return' as substrings of ordinary text must not trigger the Enter delay."""
	delays = send_keys_and_collect_delays(keys, monkeypatch)

	assert ENTER_DELAY not in delays
	assert delays == [CHAR_DELAY] * len(keys)


@pytest.mark.parametrize('keys', ['Enter', 'Return', 'enter', 'return'])
def test_enter_key_gets_the_navigation_delay(monkeypatch, keys):
	delays = send_keys_and_collect_delays(keys, monkeypatch)

	assert ENTER_DELAY in delays


def test_newline_inside_text_gets_the_navigation_delay(monkeypatch):
	delays = send_keys_and_collect_delays('line1\nline2', monkeypatch)

	assert ENTER_DELAY in delays


def test_shortcut_whose_main_key_is_enter_gets_the_navigation_delay(monkeypatch):
	delays = send_keys_and_collect_delays('Control+Enter', monkeypatch)

	assert ENTER_DELAY in delays


def test_return_shortcut_gets_the_navigation_delay(monkeypatch):
	delays = send_keys_and_collect_delays('Control+Return', monkeypatch)

	assert ENTER_DELAY in delays


def test_shortcut_whose_main_key_is_not_enter_gets_no_navigation_delay(monkeypatch):
	delays = send_keys_and_collect_delays('Control+A', monkeypatch)

	assert ENTER_DELAY not in delays
