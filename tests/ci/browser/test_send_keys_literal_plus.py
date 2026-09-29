import asyncio
from types import SimpleNamespace
from typing import cast

from browser_use.browser.events import SendKeysEvent
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog


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


def test_send_keys_literal_plus_dispatches_char_event():
	recorded_params = []
	dispatched_keys = []
	watchdog = make_watchdog(recorded_params, dispatched_keys)

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys='+')))

	char_events = [params for params in recorded_params if params.get('type') == 'char']
	assert [(params.get('text'), params.get('key')) for params in char_events] == [('+', '+')]
	assert all(params.get('key') for params in recorded_params)


def test_send_keys_text_with_plus_dispatches_all_characters():
	recorded_params = []
	dispatched_keys = []
	watchdog = make_watchdog(recorded_params, dispatched_keys)

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys='C++')))

	assert [params['text'] for params in recorded_params if params.get('type') == 'char'] == ['C', '+', '+']


def test_send_keys_control_plus_keeps_plus_as_main_key():
	recorded_params = []
	dispatched_keys = []
	watchdog = make_watchdog(recorded_params, dispatched_keys)

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys='Control++')))

	assert dispatched_keys == [
		('keyDown', 'Control', 0),
		('keyDown', '+', 2),
		('keyUp', '+', 2),
		('keyUp', 'Control', 0),
	]


def test_send_keys_existing_shortcut_and_special_key_still_work():
	recorded_params = []
	dispatched_keys = []
	watchdog = make_watchdog(recorded_params, dispatched_keys)

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys='Control+a')))
	assert dispatched_keys == [
		('keyDown', 'Control', 0),
		('keyDown', 'a', 2),
		('keyUp', 'a', 2),
		('keyUp', 'Control', 0),
	]

	recorded_params.clear()
	dispatched_keys.clear()
	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys='Enter')))
	assert dispatched_keys == [('keyDown', 'Enter', 0), ('keyUp', 'Enter', 0)]
