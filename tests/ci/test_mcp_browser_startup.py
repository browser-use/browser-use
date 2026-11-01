"""MCP tools recover when a configured browser becomes reachable after startup fails."""

import asyncio
import json
from typing import cast

import httpx
import mcp.types as types
import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.cloud.cloud import CloudBrowserClient
from browser_use.browser.cloud.views import CloudBrowserResponse
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

		retried, concurrent = await asyncio.gather(
			handler.handler(None, types.CallToolRequestParams(name='browser_list_tabs', arguments={})),  # type: ignore[arg-type]
			handler.handler(None, types.CallToolRequestParams(name='browser_list_tabs', arguments={})),  # type: ignore[arg-type]
		)
		for result in (retried, concurrent):
			assert isinstance(result, types.CallToolResult)
			assert not result.is_error
			assert isinstance(result.content[0], types.TextContent)
			assert json.loads(result.content[0].text), 'Every retry must connect to the real browser and list its tabs'
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


@pytest.mark.parametrize('owned', [True, False], ids=['created-cloud-browser', 'external-cloud-browser'])
async def test_failed_start_retries_cloud_browser(monkeypatch, tmp_path, browser_session: BrowserSession, owned):
	browser_id = '11111111-1111-1111-1111-111111111111'
	cdp_url = f'https://{browser_id}.cdp1.browser-use.com'
	active_browsers = set() if owned else {browser_id}
	created = []
	stopped = []
	discovery_requests = []
	ready = False

	async def create_browser(client, params):
		created.append(browser_id)
		active_browsers.add(browser_id)
		client.current_session_id = browser_id
		return CloudBrowserResponse(id=browser_id, status='active', liveUrl='', cdpUrl=cdp_url, timeoutAt='', startedAt='')

	async def stop_browser(client, session_id=None, extra_headers=None):
		session_id = session_id or client.current_session_id
		stopped.append(session_id)
		active_browsers.discard(session_id)
		if client.current_session_id == session_id:
			client.current_session_id = None

	async def discover_cdp(client, url, **kwargs):
		assert url == f'{cdp_url}/json/version'
		discovery_requests.append(url)
		if ready:
			return httpx.Response(200, json={'webSocketDebuggerUrl': browser_session.cdp_url}, request=httpx.Request('GET', url))
		raise httpx.ConnectError('CDP unavailable after cloud creation', request=httpx.Request('GET', url))

	# Keep the real BrowserSession startup, CDP discovery, stop/kill, and stop handler.
	# Replace only cloud API operations and the HTTP boundary of CDP discovery.
	monkeypatch.setattr(CloudBrowserClient, 'create_browser', create_browser)
	monkeypatch.setattr(CloudBrowserClient, 'stop_browser', stop_browser)
	monkeypatch.setattr(httpx.AsyncClient, 'get', discover_cdp)
	server = BrowserUseServer()
	server.config = {
		'browser_profile': {
			'use_cloud': True,
			'cdp_url': None if owned else cdp_url,
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
	result = await handler.handler(
		None,  # type: ignore[arg-type]
		types.CallToolRequestParams(name='browser_list_tabs', arguments={}),
	)
	assert isinstance(result, types.CallToolResult)
	assert result.is_error
	assert isinstance(result.content[0], types.TextContent)
	assert result.content[0].text == 'Error: CDP unavailable after cloud creation'
	assert discovery_requests == [f'{cdp_url}/json/version']
	assert server.browser_session is None
	assert server.active_sessions == {}
	assert created == ([browser_id] if owned else [])
	assert stopped == ([browser_id] if owned else [])
	assert active_browsers == (set() if owned else {browser_id})

	ready = True
	try:
		retried = await handler.handler(
			None,  # type: ignore[arg-type]
			types.CallToolRequestParams(name='browser_list_tabs', arguments={}),
		)
		assert isinstance(retried, types.CallToolResult)
		assert not retried.is_error
		assert isinstance(retried.content[0], types.TextContent)
		assert json.loads(retried.content[0].text), 'The cloud retry must connect to Chromium and list real tabs'
		assert discovery_requests == [f'{cdp_url}/json/version'] * 2
		assert created == ([browser_id, browser_id] if owned else [])
		assert stopped == ([browser_id] if owned else [])
		assert active_browsers == {browser_id}
		assert len(server.active_sessions) == 1
	finally:
		session = cast(BrowserSession | None, server.browser_session)
		if session is not None:
			if owned:
				await session.kill()
			else:
				await session.stop()
