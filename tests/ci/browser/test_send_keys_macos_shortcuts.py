"""Cmd shortcuts sent through SendKeysEvent must run their editing command on macOS.

Chrome on macOS only executes editing shortcuts such as Cmd+A when the CDP key
event names the editing command, so without it the shortcut is silently dropped.
"""

import platform

import pytest

from browser_use.browser.events import NavigateToUrlEvent, SendKeysEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

pytestmark = pytest.mark.skipif(platform.system() != 'Darwin', reason='macOS-only editing shortcut handling')


@pytest.fixture
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	await session.start()
	yield session
	await session.kill()


async def _send_keys(browser_session: BrowserSession, keys: str) -> None:
	event = browser_session.event_bus.dispatch(SendKeysEvent(keys=keys))
	await event
	await event.event_result(raise_if_any=True, raise_if_none=False)


async def test_cmd_shortcuts_edit_the_focused_input(browser_session: BrowserSession, httpserver):
	httpserver.expect_request('/input').respond_with_data('<input id="field" value="hello">', content_type='text/html')
	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/input'), new_tab=False))
	page = await browser_session.get_current_page()
	assert page is not None
	await page.evaluate("() => { const field = document.getElementById('field'); field.focus(); field.select(); }")

	async def value() -> str:
		return await page.evaluate("() => document.getElementById('field').value")

	await _send_keys(browser_session, 'Backspace')
	assert await value() == ''

	await _send_keys(browser_session, 'cmd+z')
	assert await value() == 'hello'

	await _send_keys(browser_session, 'Meta+Shift+z')
	assert await value() == ''

	await _send_keys(browser_session, 'cmd+z')
	await page.evaluate("() => { const field = document.getElementById('field'); field.setSelectionRange(5, 5); }")
	await _send_keys(browser_session, 'Meta+a')
	await _send_keys(browser_session, 'Backspace')
	assert await value() == ''
