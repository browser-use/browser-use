"""The about:blank loading animation ("DVD screensaver") can be turned off with about_blank_screensaver=False."""

import asyncio

import pytest

from browser_use.browser import BrowserProfile, BrowserSession

OVERLAY_STATE = "[!!document.getElementById('pretty-loading-animation'), document.title]"


async def _overlay_and_title(session: BrowserSession) -> list:
	cdp_session = await session.get_or_create_cdp_session(focus=False)
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': OVERLAY_STATE, 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	value = result.get('result', {}).get('value')
	assert isinstance(value, list)
	return value


async def _overlay_and_title_after_settling(session: BrowserSession) -> list:
	"""Poll for up to 5s until the overlay appears (slow CI machines), then return the final state."""
	state = await _overlay_and_title(session)
	for _ in range(50):
		if state[0]:
			break
		await asyncio.sleep(0.1)
		state = await _overlay_and_title(session)
	return state


async def _start_session(**profile_kwargs) -> BrowserSession:
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True, **profile_kwargs))
	await session.start()
	return session


def test_screensaver_is_on_by_default():
	assert BrowserProfile().about_blank_screensaver is True


async def test_screensaver_shown_on_about_blank_by_default():
	session = await _start_session()
	try:
		has_overlay, title = await _overlay_and_title_after_settling(session)
		assert has_overlay is True
		assert title.startswith('Starting agent')
	finally:
		await session.kill()


async def test_screensaver_disabled_leaves_about_blank_untouched():
	session = await _start_session(about_blank_screensaver=False)
	try:
		assert await session.get_current_page_url() == 'about:blank'
		has_overlay, title = await _overlay_and_title_after_settling(session)
		assert has_overlay is False
		assert title == ''
	finally:
		await session.kill()


@pytest.mark.parametrize('value', [True, False])
async def test_option_passes_through_browser_session_kwargs(value):
	session = BrowserSession(headless=True, about_blank_screensaver=value)
	assert session.browser_profile.about_blank_screensaver is value
