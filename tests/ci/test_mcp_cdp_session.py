"""Test MCP session ownership when attaching to an existing browser."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from browser_use.browser import BrowserSession
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
