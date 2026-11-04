"""MCP configuration and initial active tab selection."""

import asyncio
import json

import pytest
from mcp import types

from browser_use.browser import BrowserSession
from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog
from browser_use.config import load_browser_use_config
from browser_use.mcp.server import BrowserUseServer


@pytest.mark.parametrize(
	'saved,override,expected', [('active', None, 'active'), ('first', 'active', 'active'), ('active', 'first', 'first')]
)
def test_initial_tab_override_does_not_rewrite_saved_profile(monkeypatch, tmp_path, saved, override, expected):
	path = tmp_path / 'config.json'
	monkeypatch.setenv('BROWSER_USE_CONFIG_PATH', str(path))
	monkeypatch.delenv('BROWSER_USE_INITIAL_TAB', raising=False)
	load_browser_use_config()
	stored = json.loads(path.read_text())
	profile = next(profile for profile in stored['browser_profile'].values() if profile.get('default'))
	profile['initial_tab'] = saved
	path.write_text(json.dumps(stored))
	if override is not None:
		monkeypatch.setenv('BROWSER_USE_INITIAL_TAB', override)
	assert load_browser_use_config()['browser_profile']['initial_tab'] == expected
	assert json.loads(path.read_text()) == stored


@pytest.mark.integration
async def test_real_mcp_selects_active_existing_tab_and_preserves_browser(monkeypatch, tmp_path, httpserver):
	"""Exercise real startup, CDP focus detection, MCP tool calls and detach."""
	executable = LocalBrowserWatchdog._find_installed_browser_path()
	if executable is None:
		pytest.skip('Chrome/Chromium is required for CDP integration coverage')
	monkeypatch.setenv('BROWSER_USE_CONFIG_PATH', str(tmp_path / 'config.json'))
	monkeypatch.delenv('BROWSER_USE_INITIAL_TAB', raising=False)
	for name in ['a', 'b']:
		httpserver.expect_request(f'/{name}').respond_with_data(
			f'<html><head><title>Page {name}</title></head><body>Existing page {name}</body></html>', content_type='text/html'
		)
	owner = BrowserSession(
		headless=True,
		executable_path=executable,
		user_data_dir=tmp_path / 'chrome',
		enable_default_extensions=False,
		keep_alive=True,
	)
	servers = []

	def make_server(policy):
		server = BrowserUseServer()
		server.config['browser_profile'].update(
			cdp_url=owner.cdp_url,
			initial_tab=policy,
			enable_default_extensions=False,
			file_system_path=str(tmp_path / 'files'),
			downloads_path=str(tmp_path / 'downloads'),
		)
		servers.append(server)
		return server

	async def call(server: BrowserUseServer, name: str) -> str:
		handler = server.server.get_request_handler('tools/call')
		assert handler is not None
		result = await handler.handler(None, types.CallToolRequestParams(name=name, arguments={}))  # type: ignore[arg-type]
		assert isinstance(result, types.CallToolResult)
		assert not result.is_error, result.content
		return '\n'.join(part.text for part in result.content if isinstance(part, types.TextContent))

	try:
		await owner.start()
		first = await owner.get_or_create_cdp_session()
		await first.cdp_client.send.Page.navigate(params={'url': httpserver.url_for('/a')}, session_id=first.session_id)
		created = await owner.cdp_client.send.Target.createTarget(params={'url': httpserver.url_for('/b'), 'background': True})
		second = await owner.get_or_create_cdp_session(created['targetId'], focus=False)
		for page in [first, second]:
			for _ in range(100):
				ready = await page.cdp_client.send.Runtime.evaluate(
					params={'expression': 'document.title.startsWith("Page ")', 'returnByValue': True}, session_id=page.session_id
				)
				if ready['result'].get('value') is True:
					break
				await asyncio.sleep(0.05)
			else:
				pytest.fail('Local test page did not load')

		# Discover which tab the unchanged first-page policy would choose.
		default_server = make_server('first')
		await call(default_server, 'browser_get_html')
		default_session = default_server.browser_session
		assert default_session is not None
		default_id = default_session.agent_focus_target_id
		assert default_id is not None
		target_ids = {first.target_id, second.target_id}
		active_id = next(target_id for target_id in target_ids if target_id != default_id)
		await default_server._close_session(default_session.id)
		await owner.cdp_client.send.Target.activateTarget(params={'targetId': active_id})

		# Two visible windows without document focus are ambiguous in headless Chrome.
		extra = await owner.cdp_client.send.Target.createTarget(params={'url': httpserver.url_for('/a'), 'newWindow': True})
		await owner.get_or_create_cdp_session(extra['targetId'], focus=False)
		server = make_server('active')
		handler = server.server.get_request_handler('tools/call')
		assert handler is not None
		ambiguous = await handler.handler(
			None,  # type: ignore[arg-type]
			types.CallToolRequestParams(name='browser_get_html', arguments={}),
		)
		assert isinstance(ambiguous, types.CallToolResult)
		assert ambiguous.is_error
		assert 'Cannot determine a unique active tab' in str(ambiguous.content)
		assert server.active_sessions == {}
		assert {tab.target_id for tab in await owner.get_tabs()} == target_ids | {extra['targetId']}
		await owner.cdp_client.send.Target.closeTarget(params={'targetId': extra['targetId']})
		await owner.cdp_client.send.Target.activateTarget(params={'targetId': active_id})

		# Restart after failed initialization: same-server retry is covered separately by #5851.
		server = make_server('active')
		html = await call(server, 'browser_get_html')
		session = server.browser_session
		assert session is not None
		assert session.agent_focus_target_id == active_id
		assert session.session_manager.get_all_page_targets()[0].target_id != active_id
		assert {tab.target_id for tab in await session.get_tabs()} == target_ids
		expected_page = 'a' if active_id == first.target_id else 'b'
		assert f'Existing page {expected_page}' in html

		# Subsequent user focus changes must not silently redirect tool calls.
		await owner.cdp_client.send.Target.activateTarget(params={'targetId': default_id})
		assert await call(server, 'browser_get_html') == html
		assert server.browser_session is session
		await server._close_session(session.id)
		assert server.browser_session is None
		assert server.active_sessions == {}
		assert {tab.target_id for tab in await owner.get_tabs()} == target_ids
	finally:
		for server in servers:
			# Failed initialization is not tracked on main; release its event bus too.
			if server.browser_session is not None:
				await server.browser_session.stop()
			await server._close_all_sessions()
		await owner.kill()
