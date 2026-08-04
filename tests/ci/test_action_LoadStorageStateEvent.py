"""Tests for LoadStorageStateEvent handling of in-memory dict storage_state (#4257).

BrowserProfile.storage_state accepts `str | Path | dict` (profile.py), but the
load path used to stringify the profile value unconditionally, so a dict became
"{'cookies': [...]}" and failed the os.path.exists() check, silently applying
nothing. Cookies passed as a dict must reach the browser via CDP.
"""

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

TEST_COOKIE = {
	'name': 'bu_dict_state_test',
	'value': 'loaded-from-dict',
	'domain': '127.0.0.1',
	'path': '/',
	'httpOnly': False,
	'secure': False,
	'sameSite': 'Lax',
}


async def test_dict_storage_state_cookies_are_applied_on_start():
	"""storage_state passed as a dict (not a file path) must load its cookies into the browser."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=False,
			storage_state={'cookies': [TEST_COOKIE], 'origins': []},
		)
	)
	await session.start()
	try:
		cookies = await session._cdp_get_cookies()
		by_name = {c.get('name'): c for c in cookies}
		assert 'bu_dict_state_test' in by_name, (
			f'dict storage_state cookie never reached the browser; browser has {sorted(by_name)}. '
			f'The LoadStorageStateEvent path dropped the in-memory dict (#4257).'
		)
		assert by_name['bu_dict_state_test'].get('value') == 'loaded-from-dict'
		assert by_name['bu_dict_state_test'].get('domain') == '127.0.0.1'
	finally:
		await session.kill()
		await session.event_bus.stop(clear=True, timeout=5)


async def test_session_cookie_expiry_normalized_from_dict():
	"""Session cookies with expires=0/-1 in a dict storage_state must not be treated as expired."""
	session_cookie = dict(TEST_COOKIE, name='bu_session_cookie', expires=-1)
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=False,
			storage_state={'cookies': [session_cookie]},
		)
	)
	await session.start()
	try:
		cookies = await session._cdp_get_cookies()
		names = {c.get('name') for c in cookies}
		assert 'bu_session_cookie' in names, f'session cookie (expires=-1) from dict was dropped; browser has {sorted(names)}'
	finally:
		await session.kill()
		await session.event_bus.stop(clear=True, timeout=5)
