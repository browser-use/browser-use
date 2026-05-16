import logging

from bubus import EventBus

from browser_use.browser import BrowserProfile
from browser_use.browser.events import LoadStorageStateEvent, SaveStorageStateEvent
from browser_use.browser.watchdogs.storage_state_watchdog import StorageStateWatchdog


def _storage_state() -> dict:
	return {
		'cookies': [
			{
				'name': 'sessionid',
				'value': 'abc123',
				'domain': 'example.com',
				'path': '/',
				'expires': -1,
				'httpOnly': True,
				'secure': False,
				'sameSite': 'Lax',
			}
		],
		'origins': [
			{
				'origin': 'https://example.com',
				'localStorage': [{'name': 'token', 'value': 'local'}],
				'sessionStorage': [{'name': 'step', 'value': '1'}],
			}
		],
	}


def _watchdog_for_storage_state(storage_state: dict) -> tuple[StorageStateWatchdog, EventBus, list, list]:
	set_cookies_calls = []
	init_scripts = []

	class FakeBrowserSession:
		browser_profile = BrowserProfile(storage_state=storage_state, headless=True, user_data_dir=None)
		cdp_client = object()
		logger = logging.getLogger('test_storage_state_watchdog')

		async def _cdp_set_cookies(self, cookies):
			set_cookies_calls.append(cookies)

		async def _cdp_add_init_script(self, script: str):
			init_scripts.append(script)

		async def get_or_create_cdp_session(self, target_id=None, focus=None):
			return object()

		async def _cdp_get_storage_state(self):
			raise AssertionError('in-memory storage_state should not be saved as a file')

	event_bus = EventBus()
	watchdog = StorageStateWatchdog.model_construct(browser_session=FakeBrowserSession(), event_bus=event_bus)
	return watchdog, event_bus, set_cookies_calls, init_scripts


async def test_load_storage_state_accepts_in_memory_dict_from_profile():
	watchdog, event_bus, set_cookies_calls, init_scripts = _watchdog_for_storage_state(_storage_state())

	try:
		await watchdog.on_LoadStorageStateEvent(LoadStorageStateEvent())

		assert len(set_cookies_calls) == 1
		assert set_cookies_calls[0][0]['name'] == 'sessionid'
		assert 'expires' not in set_cookies_calls[0][0]
		assert len(init_scripts) == 2
		assert 'localStorage.setItem("token", "local")' in init_scripts[0]
		assert 'sessionStorage.setItem("step", "1")' in init_scripts[1]
		assert watchdog._last_cookie_state == _storage_state()['cookies']
	finally:
		await event_bus.stop(clear=True, timeout=5)


async def test_save_storage_state_skips_in_memory_dict_from_profile():
	watchdog, event_bus, _set_cookies_calls, _init_scripts = _watchdog_for_storage_state(_storage_state())

	try:
		await watchdog.on_SaveStorageStateEvent(SaveStorageStateEvent())
	finally:
		await event_bus.stop(clear=True, timeout=5)
