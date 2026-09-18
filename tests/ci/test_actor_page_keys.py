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
@pytest.mark.parametrize('prefix', ['', 'Control+'])
async def test_press_unicode_key_preserves_key_without_inventing_virtual_code(page_and_dispatch, key: str, prefix: str):
	page, dispatch = page_and_dispatch
	await page.press(prefix + key)

	params = [call.args[0] for call in dispatch.await_args_list]
	key_events = [event for event in params if event['key'] == key]
	assert [event['type'] for event in key_events] == ['keyDown', 'keyUp']
	assert all('windowsVirtualKeyCode' not in event for event in key_events)
	assert all(event['code'] == key for event in key_events)
	assert all(call.kwargs['session_id'] == 'session-1' for call in dispatch.await_args_list)
	if prefix:
		assert [(event['type'], event['key']) for event in params] == [
			('keyDown', 'Control'),
			('keyDown', key),
			('keyUp', key),
			('keyUp', 'Control'),
		]
		assert all(event['modifiers'] == 2 for event in key_events)
	else:
		assert len(params) == 2


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
