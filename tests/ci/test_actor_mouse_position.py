"""Regression tests for preserving the mouse position across button events."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from browser_use.actor.mouse import Mouse


def _mouse() -> tuple[Mouse, AsyncMock]:
	dispatch_mouse_event = AsyncMock()
	input_domain = SimpleNamespace(dispatchMouseEvent=dispatch_mouse_event)
	client = SimpleNamespace(send=SimpleNamespace(Input=input_domain))
	browser_session: Any = SimpleNamespace(cdp_client=client)
	return Mouse(browser_session, session_id='session-id'), dispatch_mouse_event


async def test_down_and_up_use_position_from_last_move():
	mouse, dispatch_mouse_event = _mouse()

	await mouse.move(320, 240)
	await mouse.down()
	await mouse.up()

	assert [call.args[0] for call in dispatch_mouse_event.await_args_list] == [
		{'type': 'mouseMoved', 'x': 320, 'y': 240},
		{'type': 'mousePressed', 'x': 320, 'y': 240, 'button': 'left', 'clickCount': 1},
		{'type': 'mouseReleased', 'x': 320, 'y': 240, 'button': 'left', 'clickCount': 1},
	]


async def test_button_events_use_position_from_last_click():
	mouse, dispatch_mouse_event = _mouse()

	await mouse.click(75, 125)
	await mouse.down(button='right')
	await mouse.up(button='right')

	assert [call.args[0] for call in dispatch_mouse_event.await_args_list[2:]] == [
		{'type': 'mousePressed', 'x': 75, 'y': 125, 'button': 'right', 'clickCount': 1},
		{'type': 'mouseReleased', 'x': 75, 'y': 125, 'button': 'right', 'clickCount': 1},
	]


async def test_button_events_default_to_origin_before_mouse_moves():
	mouse, dispatch_mouse_event = _mouse()

	await mouse.down()
	await mouse.up()

	assert [call.args[0] for call in dispatch_mouse_event.await_args_list] == [
		{'type': 'mousePressed', 'x': 0, 'y': 0, 'button': 'left', 'clickCount': 1},
		{'type': 'mouseReleased', 'x': 0, 'y': 0, 'button': 'left', 'clickCount': 1},
	]


async def test_failed_move_does_not_update_mouse_position():
	mouse, dispatch_mouse_event = _mouse()
	dispatch_mouse_event.side_effect = [None, RuntimeError('CDP move failed'), None]

	await mouse.move(10, 20)
	with pytest.raises(RuntimeError, match='CDP move failed'):
		await mouse.move(30, 40)
	await mouse.down()

	assert dispatch_mouse_event.await_args_list[-1].args[0] == {
		'type': 'mousePressed',
		'x': 10,
		'y': 20,
		'button': 'left',
		'clickCount': 1,
	}
