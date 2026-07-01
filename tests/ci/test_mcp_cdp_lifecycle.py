"""Regression tests for MCP CDP runtime configuration and session lifecycle."""

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from browser_use.config import load_browser_use_config
from browser_use.mcp import server as server_module
from browser_use.mcp.config import build_mcp_config_overrides
from browser_use.mcp.server import BrowserUseServer


@pytest.fixture(autouse=True)
def isolated_browser_use_config(tmp_path, monkeypatch):
	"""Keep MCP config reads/writes out of the developer's real home dir."""
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'browseruse-config'))
	monkeypatch.delenv('BROWSER_USE_CDP_URL', raising=False)
	monkeypatch.delenv('BROWSER_USE_HEADLESS', raising=False)
	monkeypatch.delenv('BROWSER_USE_ALLOWED_DOMAINS', raising=False)
	monkeypatch.delenv('BROWSER_USE_LLM_MODEL', raising=False)


def test_mcp_cli_overrides_include_cdp_url_and_do_not_use_interactive_config_shape() -> None:
	overrides = build_mcp_config_overrides(
		{
			'model': 'gpt-4.1-mini',
			'headless': True,
			'user_data_dir': '/tmp/browser-profile',
			'profile_directory': 'Default',
			'cdp_url': 'http://127.0.0.1:9223',
			'window_width': 1280,
			'window_height': 720,
			'proxy_url': 'http://proxy.internal:8080',
			'no_proxy': 'localhost, 127.0.0.1',
			'proxy_username': 'alice',
			'proxy_password': 'secret',
		}
	)

	assert overrides == {
		'browser_profile': {
			'headless': True,
			'user_data_dir': '/tmp/browser-profile',
			'profile_directory': 'Default',
			'cdp_url': 'http://127.0.0.1:9223',
			'window_size': {'width': 1280, 'height': 720},
			'proxy': {
				'server': 'http://proxy.internal:8080',
				'bypass': 'localhost,127.0.0.1',
				'username': 'alice',
				'password': 'secret',
			},
		},
		'llm': {'model': 'gpt-4.1-mini'},
	}
	assert 'browser' not in overrides
	assert 'model' not in overrides


def test_mcp_server_applies_transient_cli_overrides() -> None:
	server = BrowserUseServer(
		config_overrides={
			'browser_profile': {'cdp_url': 'http://127.0.0.1:9223', 'headless': True},
			'llm': {'model': 'gpt-4.1-mini'},
		}
	)

	assert server.config['browser_profile']['cdp_url'] == 'http://127.0.0.1:9223'
	assert server.config['browser_profile']['headless'] is True
	assert server.config['llm']['model'] == 'gpt-4.1-mini'


def test_mcp_config_supports_cdp_url_environment_override(monkeypatch) -> None:
	monkeypatch.setenv('BROWSER_USE_CDP_URL', 'http://127.0.0.1:9223')

	config = load_browser_use_config()

	assert config['browser_profile']['cdp_url'] == 'http://127.0.0.1:9223'


async def test_direct_browser_tools_reinitialize_stale_session() -> None:
	server = BrowserUseServer()
	calls: list[str] = []

	class StaleSession:
		id = 'stale-session'
		is_cdp_connected = False
		session_manager = None
		agent_focus_target_id = None

		async def reset(self) -> None:
			calls.append('reset-stale')

		async def get_tabs(self) -> list[Any]:
			return []

	class ReadySession:
		id = 'ready-session'
		is_cdp_connected = True
		session_manager = object()
		agent_focus_target_id = 'target-1234'

		async def get_tabs(self) -> list[Any]:
			return [SimpleNamespace(target_id='target-1234', url='https://example.com', title='Example Domain')]

	async def fake_init_browser_session(*_args: Any, **_kwargs: Any) -> None:
		calls.append('init-ready')
		server.browser_session = ReadySession()  # type: ignore[assignment]

	server.browser_session = StaleSession()  # type: ignore[assignment]
	server.active_sessions['stale-session'] = {'session': server.browser_session}
	server._init_browser_session = fake_init_browser_session  # type: ignore[method-assign]

	result = await server._execute_tool('browser_list_tabs', {})

	assert calls == ['init-ready']
	assert json.loads(cast(str, result)) == [
		{'tab_id': '1234', 'url': 'https://example.com', 'title': 'Example Domain'},
	]


async def test_failed_browser_start_does_not_leave_partial_session(monkeypatch) -> None:
	reset_calls = 0

	class FailingBrowserSession:
		id = 'failed-session'
		is_cdp_connected = False
		session_manager = None
		agent_focus_target_id = None

		def __init__(self, **_kwargs: Any) -> None:
			pass

		async def start(self) -> None:
			raise RuntimeError('connect failed')

		async def reset(self) -> None:
			nonlocal reset_calls
			reset_calls += 1

	monkeypatch.setattr(server_module, 'BrowserSession', FailingBrowserSession)
	server = BrowserUseServer()

	with pytest.raises(RuntimeError, match='connect failed'):
		await server._init_browser_session()

	assert reset_calls == 1
	assert server.browser_session is None
	assert server.active_sessions == {}
