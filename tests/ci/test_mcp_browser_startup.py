"""MCP tools recover when a configured browser becomes reachable after startup fails."""

import asyncio
import json

import mcp.types as types
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.mcp.server import BrowserUseServer


async def test_tools_retry_failed_browser_start(httpserver: HTTPServer, browser_session: BrowserSession, tmp_path):
	server = BrowserUseServer()
	server.config = {
		'browser_profile': {
			'cdp_url': httpserver.url_for('/'),
			'user_data_dir': str(tmp_path / 'profile'),
			'file_system_path': str(tmp_path / 'files'),
			'downloads_path': str(tmp_path / 'downloads'),
			'headless': True,
			'enable_default_extensions': False,
		},
		'llm': {},
	}
	handler = server.server.get_request_handler('tools/call')
	assert handler is not None
	httpserver.expect_request('/json/version').respond_with_json({'error': 'browser unavailable'}, status=503)

	try:
		failed = await handler.handler(
			None,  # type: ignore[arg-type]
			types.CallToolRequestParams(name='browser_list_tabs', arguments={}),
		)
		assert isinstance(failed, types.CallToolResult)
		assert failed.is_error

		# The same endpoint becomes ready without restarting the MCP server.
		httpserver.clear()
		httpserver.expect_request('/json/version').respond_with_json({'webSocketDebuggerUrl': browser_session.cdp_url})
		httpserver.expect_request('/page').respond_with_data(
			'<title>Retry ready</title><button>Recovered</button>', content_type='text/html'
		)

		retried, _ = await asyncio.gather(
			handler.handler(None, types.CallToolRequestParams(name='browser_list_tabs', arguments={})),  # type: ignore[arg-type]
			handler.handler(None, types.CallToolRequestParams(name='browser_list_tabs', arguments={})),  # type: ignore[arg-type]
		)
		assert isinstance(retried, types.CallToolResult)
		assert not retried.is_error
		assert isinstance(retried.content[0], types.TextContent)
		assert json.loads(retried.content[0].text), 'The retry must connect to the real browser and list its tabs'
		sessions = await handler.handler(
			None,  # type: ignore[arg-type]
			types.CallToolRequestParams(name='browser_list_sessions', arguments={}),
		)
		assert isinstance(sessions, types.CallToolResult)
		assert isinstance(sessions.content[0], types.TextContent)
		assert len(json.loads(sessions.content[0].text)) == 1, 'Concurrent retries must not create duplicate sessions'

		await handler.handler(
			None,  # type: ignore[arg-type]
			types.CallToolRequestParams(name='browser_navigate', arguments={'url': httpserver.url_for('/page')}),
		)
		state = await handler.handler(
			None,  # type: ignore[arg-type]
			types.CallToolRequestParams(name='browser_get_state', arguments={'include_screenshot': True}),
		)
		assert isinstance(state, types.CallToolResult)
		assert not state.is_error
		assert any(isinstance(part, types.TextContent) and 'Recovered' in part.text for part in state.content)
		assert any(isinstance(part, types.ImageContent) and part.data for part in state.content)
	finally:
		if server.browser_session is not None:
			await server.browser_session.stop()
