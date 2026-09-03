import asyncio
from types import SimpleNamespace

from browser_use.browser.events import SendKeysEvent
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog


def test_send_keys_literal_plus_dispatches_char_event():
	recorded_params = []
	dispatched_keys = []

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
		_get_char_modifiers_and_vk=lambda char: (0, 0, char),
		_get_key_code_for_char=lambda key: f'Key{key.upper()}',
	)

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys='+')))

	assert any(params.get('type') == 'char' and params.get('text') == '+' for params in recorded_params), (
		recorded_params,
		dispatched_keys,
	)


def test_send_keys_text_containing_enter_has_no_enter_delay(monkeypatch):
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

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys='center')))

	enter_delays = [delay for delay in delays if delay == 0.1]
	assert enter_delays == []
