import asyncio
from types import SimpleNamespace

import pytest

from browser_use.browser.events import SendKeysEvent
from browser_use.browser.watchdogs.default_action_watchdog import (
	DefaultActionWatchdog,
)


def _build_mock_watchdog(delays: list[float]):
	async def sleep(delay):
		delays.append(delay)

	class Input:
		async def dispatchKeyEvent(
			self,
			params=None,
			session_id=None,
		):
			return None

	cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(
			send=SimpleNamespace(Input=Input()),
		),
		session_id="session-1",
	)

	class BrowserSession:
		async def get_or_create_cdp_session(self, focus=False):
			return cdp_session

	async def dispatch_key_event(
		_session,
		event_type,
		key,
		modifiers=0,
	):
		return None

	return SimpleNamespace(
		browser_session=BrowserSession(),
		logger=SimpleNamespace(
			info=lambda *args, **kwargs: None,
		),
		_dispatch_key_event=dispatch_key_event,
		_get_char_modifiers_and_vk=lambda char: (0, 0, char),
		_get_key_code_for_char=lambda key: f"Key{key.upper()}",
	), sleep


@pytest.mark.parametrize(
	"text",
	[
		"center",
		"enterprise",
		"returning",
		"carpenter",
		"hello world",
	],
)
def test_send_keys_text_containing_enter_has_no_enter_delay(
	monkeypatch,
	text,
):
	delays = []
	watchdog, sleep = _build_mock_watchdog(delays)
	monkeypatch.setattr(asyncio, "sleep", sleep)

	asyncio.run(
		DefaultActionWatchdog.on_SendKeysEvent(
			watchdog,
			SendKeysEvent(keys=text),
		)
	)

	enter_delays = [delay for delay in delays if delay == 0.1]
	assert enter_delays == [], f"Expected no 0.1s enter delay for text {text!r}, got {enter_delays}"


@pytest.mark.parametrize(
	"key",
	[
		"Enter",
		"enter",
		"ENTER",
		"Return",
		"return",
		"ctrl+enter",
		"Control+Enter",
		"cmd+Return",
	],
)
def test_send_keys_enter_key_triggers_delay(
	monkeypatch,
	key,
):
	delays = []
	watchdog, sleep = _build_mock_watchdog(delays)
	monkeypatch.setattr(asyncio, "sleep", sleep)

	asyncio.run(
		DefaultActionWatchdog.on_SendKeysEvent(
			watchdog,
			SendKeysEvent(keys=key),
		)
	)

	enter_delays = [delay for delay in delays if delay == 0.1]
	assert enter_delays == [0.1], f"Expected 0.1s enter delay for key {key!r}, got {enter_delays}"
