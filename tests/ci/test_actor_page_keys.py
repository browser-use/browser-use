"""Regression tests for keyboard events dispatched by Page.press."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.actor.page import Page


@pytest.fixture
def page_and_dispatch() -> tuple[Page, AsyncMock]:
	dispatch = AsyncMock(return_value={})
	browser_session = MagicMock()
	browser_session.cdp_client.send.Input.dispatchKeyEvent = dispatch
	page = Page(browser_session, target_id='target-1', session_id='session-1')
	return page, dispatch


@pytest.mark.parametrize('key', ['ß', 'ﬃ', 'é', '中', '٢', '²'])
async def test_press_printable_unicode_key_dispatches_char_event(page_and_dispatch, key: str):
	page, dispatch = page_and_dispatch
	await page.press(key)

	params = [call.args[0] for call in dispatch.await_args_list]
	key_events = [event for event in params if event['key'] == key]
	assert [event['type'] for event in key_events] == ['keyDown', 'char', 'keyUp']
	physical_key_events = [event for event in key_events if event['type'] != 'char']
	assert all('windowsVirtualKeyCode' not in event for event in physical_key_events)
	assert all(event['code'] == key for event in physical_key_events)
	assert params[1] == {'type': 'char', 'text': key, 'key': key}
	assert all(call.kwargs['session_id'] == 'session-1' for call in dispatch.await_args_list)
	assert len(params) == 3


@pytest.mark.parametrize('key', ['ß', '中'])
async def test_press_unicode_key_with_modifier_does_not_dispatch_char_event(page_and_dispatch, key: str):
	page, dispatch = page_and_dispatch
	await page.press('Control+' + key)

	params = [call.args[0] for call in dispatch.await_args_list]
	key_events = [event for event in params if event['key'] == key]
	assert [(event['type'], event['key']) for event in params] == [
		('keyDown', 'Control'),
		('keyDown', key),
		('keyUp', key),
		('keyUp', 'Control'),
	]
	assert all('windowsVirtualKeyCode' not in event for event in key_events)
	assert all(event['modifiers'] == 2 for event in key_events)


async def test_press_unicode_key_inserts_text_into_focused_input(browser_session, httpserver):
	httpserver.expect_request('/unicode-input').respond_with_data(
		'<input id="target" autofocus>',
		content_type='text/html',
	)
	await browser_session.navigate_to(httpserver.url_for('/unicode-input'))

	page = await browser_session.must_get_current_page()
	await page.press('ß')

	assert await page.evaluate('() => document.querySelector("#target").value') == 'ß'


@pytest.mark.parametrize(
	('key', 'code', 'vk_code'),
	[('a', 'KeyA', 65), ('A', 'KeyA', 65), ('1', 'Digit1', 49), ('Enter', 'Enter', 13), ('ArrowLeft', 'ArrowLeft', 37)],
)
async def test_press_ascii_and_named_keys_keep_virtual_codes(page_and_dispatch, key: str, code: str, vk_code: int):
	page, dispatch = page_and_dispatch
	await page.press(key)

	params = [call.args[0] for call in dispatch.await_args_list]
	assert params == [
		{'type': 'keyDown', 'key': key, 'code': code, 'windowsVirtualKeyCode': vk_code},
		{'type': 'keyUp', 'key': key, 'code': code, 'windowsVirtualKeyCode': vk_code},
	]
