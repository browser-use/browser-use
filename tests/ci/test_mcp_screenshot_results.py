import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp import types

from browser_use.mcp.client import MCPClient
from browser_use.mcp.server import BrowserUseServer


class _FakePageInfo:
	viewport_width = 1280
	viewport_height = 720
	page_width = 1280
	page_height = 2000
	scroll_x = 0
	scroll_y = 120


class _FakeDOMState:
	selector_map = {}


class _FakeState:
	url = 'https://example.com'
	title = 'Example'
	tabs = [SimpleNamespace(url='https://example.com', title='Example')]
	dom_state = _FakeDOMState()
	page_info = _FakePageInfo()

	def __init__(self, screenshot: str | None):
		self.screenshot = screenshot


@pytest.mark.asyncio
async def test_get_browser_state_writes_screenshot_to_file(tmp_path: Path):
	server = BrowserUseServer()
	server._mcp_screenshot_dir = tmp_path

	screenshot_b64 = base64.b64encode(b'png-bytes').decode()
	server.browser_session = SimpleNamespace(get_browser_state_summary=AsyncMock(return_value=_FakeState(screenshot_b64)))

	state_json, screenshot_b64_result = await server._get_browser_state(include_screenshot=True)
	payload = json.loads(state_json)

	assert screenshot_b64_result is None
	assert payload['screenshot_path'].endswith('.png')
	assert screenshot_b64 not in state_json
	assert Path(payload['screenshot_path']).read_bytes() == b'png-bytes'


@pytest.mark.asyncio
async def test_screenshot_writes_file_reference_instead_of_inline_base64(tmp_path: Path):
	server = BrowserUseServer()
	server._mcp_screenshot_dir = tmp_path
	server._update_session_activity = lambda *_args, **_kwargs: None
	server.browser_session = SimpleNamespace(
		id='session-1',
		take_screenshot=AsyncMock(return_value=b'fresh-png'),
		get_browser_state_summary=AsyncMock(return_value=_FakeState(None)),
	)

	meta_json, screenshot_b64_result = await server._screenshot(full_page=False)
	payload = json.loads(meta_json)
	screenshot_b64 = base64.b64encode(b'fresh-png').decode()

	assert screenshot_b64_result is None
	assert payload['screenshot_path'].endswith('.png')
	assert payload['size_bytes'] == len(b'fresh-png')
	assert screenshot_b64 not in meta_json
	assert Path(payload['screenshot_path']).read_bytes() == b'fresh-png'


@pytest.mark.asyncio
async def test_close_session_removes_persisted_screenshots(tmp_path: Path):
	server = BrowserUseServer()
	screenshot_path = tmp_path / 'browser-use-screenshot-test.png'
	screenshot_path.write_bytes(b'png-bytes')
	session = SimpleNamespace(close=AsyncMock())
	server.active_sessions['session-1'] = {
		'session': session,
		'created_at': 0,
		'last_activity': 0,
		'url': 'https://example.com',
		'screenshot_paths': [str(screenshot_path)],
	}
	server.browser_session = SimpleNamespace(id='session-1')

	result = await server._close_session('session-1')

	assert result == 'Successfully closed session session-1'
	assert not screenshot_path.exists()
	assert 'session-1' not in server.active_sessions


def test_mcp_client_extracts_images_without_inlining_base64():
	client = MCPClient(server_name='test', command='echo')
	result = SimpleNamespace(
		content=[
			types.TextContent(type='text', text='Viewport metadata'),
			types.ImageContent(type='image', data='abc123', mimeType='image/png'),
		]
	)

	text, images = client._extract_mcp_result_payload(result)

	assert text == 'Viewport metadata'
	assert images == [{'name': 'mcp-image-2.png', 'data': 'abc123'}]
