"""Test MCP session ownership when attaching to an existing browser."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from browser_use.browser import BrowserSession
from browser_use.browser.events import NavigateToUrlEvent
from browser_use.mcp.server import BrowserUseServer


@pytest.mark.parametrize('cdp_url', [None, 'http://localhost:9222'])
async def test_mcp_session_retains_remote_endpoint_on_reset(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cdp_url: str | None
) -> None:
	"""Reset preserves a configured endpoint while local sessions stay local."""
	monkeypatch.setenv('BROWSER_USE_CONFIG_PATH', str(tmp_path / 'config.json'))
	if cdp_url:
		monkeypatch.setenv('BROWSER_USE_CDP_URL', cdp_url)
	else:
		monkeypatch.delenv('BROWSER_USE_CDP_URL', raising=False)
	monkeypatch.setattr(BrowserSession, 'start', AsyncMock())
	server = BrowserUseServer()
	server.config['browser_profile']['file_system_path'] = str(tmp_path / 'files')
	await server._init_browser_session()
	assert server.browser_session is not None
	assert server.browser_session.is_local is (cdp_url is None)
	await server.browser_session.reset()
	assert server.browser_session.cdp_url == cdp_url


async def test_mcp_attaches_and_reconnects_to_existing_browser(
	monkeypatch: pytest.MonkeyPatch, tmp_path: Path, browser_session: BrowserSession, httpserver
) -> None:
	"""A real MCP attachment preserves the existing tab across stop and restart."""
	httpserver.expect_request('/existing').respond_with_data(
		'<html><head><title>Existing MCP tab</title></head><body>Existing session</body></html>',
		content_type='text/html',
	)
	url = httpserver.url_for('/existing')
	event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url))
	await event.event_result(raise_if_any=True, raise_if_none=False)
	before = await browser_session.get_tabs()
	existing = next(tab for tab in before if tab.url == url)
	assert browser_session.cdp_url
	monkeypatch.setenv('BROWSER_USE_CONFIG_PATH', str(tmp_path / 'config.json'))
	monkeypatch.setenv('BROWSER_USE_CDP_URL', browser_session.cdp_url)
	server = BrowserUseServer()
	server.config['browser_profile']['file_system_path'] = str(tmp_path / 'files')
	try:
		await server._init_browser_session()
		attached = server.browser_session
		assert attached is not None
		assert not attached.is_local
		assert {tab.target_id for tab in await attached.get_tabs()} == {tab.target_id for tab in before}
		tabs = json.loads(await server._list_tabs())
		assert any(tab['tab_id'] == existing.target_id[-4:] and tab['url'] == url for tab in tabs)
		endpoint = attached.cdp_url
		await attached.stop()
		assert attached.cdp_url == endpoint
		await attached.start()
		assert any(tab.target_id == existing.target_id for tab in await attached.get_tabs())
	finally:
		if server.browser_session is not None:
			await server.browser_session.stop()
