"""Editing commands must follow the CDP browser OS, not the client OS.

Chrome only runs Cmd editing shortcuts when the key event names the command,
and that behavior belongs to the browser host. A remote macOS browser reached
from a non-macOS client (or the reverse) must still get the right events.
"""

import asyncio
import platform
from types import SimpleNamespace
from typing import cast

import pytest

from browser_use.browser.events import SendKeysEvent
from browser_use.browser.watchdogs import default_action_watchdog as watchdog_module
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog

MAC_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'
WINDOWS_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'


def make_watchdog(recorded_params, browser_user_agent: str) -> DefaultActionWatchdog:
	class Input:
		async def dispatchKeyEvent(self, params=None, session_id=None):
			recorded_params.append(params or {})

	class Browser:
		async def getVersion(self):
			return {'userAgent': browser_user_agent}

	class Runtime:
		def __init__(self):
			self.calls = 0

		async def callFunctionOn(self, params=None, session_id=None):
			self.calls += 1
			if self.calls == 1:
				return {'result': {'value': {'cleared': False, 'method': 'none'}}}
			return {'result': {'value': None}}

	cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(send=SimpleNamespace(Input=Input(), Browser=Browser(), Runtime=Runtime())),
		session_id='session-1',
	)

	class BrowserSession:
		async def get_or_create_cdp_session(self, target_id=None, focus=False):
			return cdp_session

	watchdog = SimpleNamespace(
		browser_session=BrowserSession(),
		logger=SimpleNamespace(info=lambda *args, **kwargs: None, debug=lambda *args, **kwargs: None),
	)
	watchdog._dispatch_key_event = DefaultActionWatchdog._dispatch_key_event.__get__(watchdog)
	if hasattr(DefaultActionWatchdog, '_is_macos_browser'):
		watchdog._is_macos_browser = DefaultActionWatchdog._is_macos_browser.__get__(watchdog)
	watchdog._cdp_session = cdp_session
	return cast(DefaultActionWatchdog, watchdog)


def set_client_os(monkeypatch, system: str) -> None:
	monkeypatch.setattr(platform, 'system', lambda: system)
	assert watchdog_module.platform.system() == system


@pytest.mark.parametrize(
	('keys', 'main_key', 'command'),
	[
		('Meta+a', 'a', 'selectAll'),
		('Meta+z', 'z', 'undo'),
		('Meta+Shift+z', 'z', 'redo'),
	],
)
def test_send_keys_names_editing_command_when_browser_is_macos(monkeypatch, keys, main_key, command):
	set_client_os(monkeypatch, 'Windows')
	recorded_params = []
	watchdog = make_watchdog(recorded_params, MAC_UA)

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys=keys)))

	main_key_downs = [p for p in recorded_params if p.get('type') == 'keyDown' and p.get('key') == main_key]
	assert len(main_key_downs) == 1
	assert main_key_downs[0].get('commands') == [command]
	assert main_key_downs[0].get('modifiers') == (12 if 'Shift' in keys else 4)


def test_send_keys_omits_editing_command_when_browser_is_not_macos(monkeypatch):
	set_client_os(monkeypatch, 'Darwin')
	recorded_params = []
	watchdog = make_watchdog(recorded_params, WINDOWS_UA)

	asyncio.run(DefaultActionWatchdog.on_SendKeysEvent(watchdog, SendKeysEvent(keys='Meta+a')))

	main_key_downs = [p for p in recorded_params if p.get('type') == 'keyDown' and p.get('key') == 'a']
	assert len(main_key_downs) == 1
	assert 'commands' not in main_key_downs[0]
	assert main_key_downs[0].get('modifiers') == 4


def test_clear_text_field_last_resort_names_select_all_when_browser_is_macos(monkeypatch):
	set_client_os(monkeypatch, 'Windows')
	recorded_params = []
	watchdog = make_watchdog(recorded_params, MAC_UA)

	result = asyncio.run(DefaultActionWatchdog._clear_text_field(watchdog, object_id='obj-1', cdp_session=watchdog._cdp_session))

	assert result is True
	select_all_downs = [p for p in recorded_params if p.get('type') == 'keyDown' and p.get('key') == 'a']
	assert len(select_all_downs) == 1
	assert select_all_downs[0].get('modifiers') == 4
	assert select_all_downs[0].get('commands') == ['selectAll']


def test_clear_text_field_last_resort_uses_ctrl_when_browser_is_not_macos(monkeypatch):
	set_client_os(monkeypatch, 'Darwin')
	recorded_params = []
	watchdog = make_watchdog(recorded_params, WINDOWS_UA)

	result = asyncio.run(DefaultActionWatchdog._clear_text_field(watchdog, object_id='obj-1', cdp_session=watchdog._cdp_session))

	assert result is True
	select_all_downs = [p for p in recorded_params if p.get('type') == 'keyDown' and p.get('key') == 'a']
	assert len(select_all_downs) == 1
	assert select_all_downs[0].get('modifiers') == 2
	assert 'commands' not in select_all_downs[0]
