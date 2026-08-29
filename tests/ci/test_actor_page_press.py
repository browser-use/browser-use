"""Tests for Page.press keyboard event dispatch."""

from typing import Any, cast

import pytest

from browser_use.actor.page import Page


class _Input:
	def __init__(self) -> None:
		self.events: list[dict[str, object]] = []

	async def dispatchKeyEvent(self, params: dict[str, object], *, session_id: str) -> None:
		self.events.append(params)


class _Client:
	def __init__(self) -> None:
		self.send = type('Send', (), {'Input': _Input()})()


class _BrowserSession:
	def __init__(self) -> None:
		self.cdp_client = _Client()


@pytest.mark.asyncio
async def test_press_literal_plus_dispatches_plus_key() -> None:
	input_client = _Input()
	browser_session = _BrowserSession()
	cast(Any, browser_session.cdp_client.send).Input = input_client
	page = Page(cast(Any, browser_session), 'target', session_id='session')

	await page.press('+')

	events = input_client.events
	assert [event['type'] for event in events] == ['keyDown', 'keyUp']
	assert [event['key'] for event in events] == ['+', '+']
	assert [event['code'] for event in events] == ['+', '+']
