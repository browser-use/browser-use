import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from browser_use.mcp.server import BrowserUseServer


class _FakeElement:
	tag_name = 'button'
	attributes = {'placeholder': 'Search', 'href': '/next'}

	def get_all_children_text(self, max_depth: int) -> str:
		return f'Click me depth={max_depth}'


class _FakeDOMState:
	selector_map = {7: _FakeElement()}


class _FakePageInfo:
	viewport_width = 1280
	viewport_height = 720
	page_width = 1280
	page_height = 2000
	scroll_x = 0
	scroll_y = 120


class _FakeState:
	url = 'https://example.com'
	title = 'Example'
	tabs = [SimpleNamespace(url='https://example.com', title='Example')]
	dom_state = _FakeDOMState()
	page_info = _FakePageInfo()

	def __init__(self, screenshot: str | None):
		self.screenshot = screenshot


def _server_with_session(session: SimpleNamespace) -> BrowserUseServer:
	server = object.__new__(BrowserUseServer)
	cast(Any, server).browser_session = session
	return server


@pytest.mark.asyncio
async def test_get_browser_state_does_not_capture_screenshot_by_default():
	session = SimpleNamespace(get_browser_state_summary=AsyncMock(return_value=_FakeState('ignored-image-data')))
	server = _server_with_session(session)

	state_json, screenshot = await server._get_browser_state()
	payload = json.loads(state_json)

	session.get_browser_state_summary.assert_awaited_once_with(include_screenshot=False)
	assert screenshot is None
	assert 'screenshot_dimensions' not in payload
	assert payload['interactive_elements'] == [
		{
			'index': 7,
			'tag': 'button',
			'text': 'Click me depth=2',
			'placeholder': 'Search',
			'href': '/next',
		}
	]


@pytest.mark.asyncio
async def test_get_browser_state_captures_screenshot_when_requested():
	session = SimpleNamespace(get_browser_state_summary=AsyncMock(return_value=_FakeState('image-data')))
	server = _server_with_session(session)

	state_json, screenshot = await server._get_browser_state(include_screenshot=True)
	payload = json.loads(state_json)

	session.get_browser_state_summary.assert_awaited_once_with(include_screenshot=True)
	assert screenshot == 'image-data'
	assert payload['screenshot_dimensions'] == {'width': 1280, 'height': 720}
