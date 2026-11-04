"""Regression coverage for MCP agent recovery in the active browser session (#6295)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import mcp.types as types
import pytest

from browser_use.browser import BrowserSession
from browser_use.mcp import server as server_module
from browser_use.mcp.server import BrowserUseServer


@pytest.fixture
def setup_server(monkeypatch: pytest.MonkeyPatch):
	server = BrowserUseServer()
	server.config = {'llm': {'api_key': 'test-key'}, 'browser_profile': {'allowed_domains': ['example.test']}}
	monkeypatch.setattr(server_module, 'ChatOpenAI', MagicMock())
	history = MagicMock()
	history.history = []
	history.is_successful.return_value = True
	history.final_result.return_value = 'Recovered'
	history.errors.return_value = []
	history.urls.return_value = []
	agent = MagicMock()
	agent.run = AsyncMock(return_value=history)
	agent.close = AsyncMock()
	factory = MagicMock(return_value=agent)
	monkeypatch.setattr(server_module, 'Agent', factory)
	return server, factory, agent


@pytest.mark.parametrize('fails', [False, True])
async def test_retry_reuses_active_session_and_preserves_its_lifetime(setup_server, fails: bool):
	server, factory, agent = setup_server
	session = BrowserSession(keep_alive=False, allowed_domains=['example.test'])
	server.browser_session = session
	server._track_session(session)

	async def run(**kwargs):
		assert session.browser_profile.keep_alive is True
		# A long recovery task must not be mistaken for an idle session.
		server.active_sessions[session.id]['last_activity'] = 0
		await server._cleanup_expired_sessions()
		assert session.id in server.active_sessions
		if fails:
			raise RuntimeError('agent failed')
		return agent.run.return_value

	async def close():
		assert session.browser_profile.keep_alive is True

	agent.run.side_effect = run
	agent.close.side_effect = close
	result = await server._execute_tool('retry_with_browser_use_agent', {'task': 'Continue the form', 'max_steps': 3})

	assert factory.call_args.kwargs.get('browser_session') is session
	assert server.browser_session is session
	assert session.browser_profile.keep_alive is False
	assert server._agent_session is None
	assert session.browser_profile.allowed_domains == ['example.test']
	agent.run.assert_awaited_once_with(max_steps=3)
	agent.close.assert_awaited_once()
	assert ('Agent task failed' if fails else 'Recovered') in result


async def test_retry_can_explicitly_use_a_separate_session(setup_server):
	server, factory, _ = setup_server
	session = BrowserSession(keep_alive=False, allowed_domains=['original.test'])
	server.browser_session = session
	await server._execute_tool(
		'retry_with_browser_use_agent',
		{'task': 'Start over', 'same_tab': False, 'allowed_domains': ['new.test']},
	)
	assert factory.call_args.kwargs.get('browser_session') is None
	assert factory.call_args.kwargs['browser_profile'].allowed_domains == ['new.test']
	assert server.browser_session is session
	assert session.browser_profile.allowed_domains == ['original.test']
	assert session.browser_profile.keep_alive is False
	assert server.config['browser_profile']['allowed_domains'] == ['example.test']


async def test_concurrent_retries_do_not_race_shared_session_cleanup(setup_server):
	server, _, agent = setup_server
	session = BrowserSession(keep_alive=False)
	server.browser_session = session
	active = 0

	async def run(**kwargs):
		nonlocal active
		active += 1
		await asyncio.sleep(0)
		assert active == 1
		assert session.browser_profile.keep_alive is True
		active -= 1
		return agent.run.return_value

	agent.run.side_effect = run
	results = await asyncio.gather(
		server._execute_tool('retry_with_browser_use_agent', {'task': 'First retry'}),
		server._execute_tool('retry_with_browser_use_agent', {'task': 'Second retry'}),
	)
	assert all('Recovered' in result for result in results)
	assert session.browser_profile.keep_alive is False


async def test_cleanup_error_restores_session_settings(setup_server):
	server, _, agent = setup_server
	session = BrowserSession(keep_alive=False)
	server.browser_session = session
	agent.close.side_effect = RuntimeError('cleanup failed')
	with pytest.raises(RuntimeError, match='cleanup failed'):
		await server._execute_tool('retry_with_browser_use_agent', {'task': 'Continue'})
	assert session.browser_profile.keep_alive is False
	assert server._agent_session is None


async def test_retry_without_an_active_session_keeps_profile_defaults(setup_server):
	server, factory, _ = setup_server
	await server._execute_tool('retry_with_browser_use_agent', {'task': 'Start a task', 'allowed_domains': []})
	assert factory.call_args.kwargs.get('browser_session') is None
	assert factory.call_args.kwargs['browser_profile'].allowed_domains == ['example.test']


@pytest.mark.parametrize('allowed_domains', [None, [], ['example.test']])
async def test_reusing_session_preserves_domain_policy(setup_server, allowed_domains):
	server, factory, _ = setup_server
	session = BrowserSession(keep_alive=True, allowed_domains=['example.test'])
	server.browser_session = session
	await server._execute_tool('retry_with_browser_use_agent', {'task': 'Continue', 'allowed_domains': allowed_domains})
	assert factory.call_args.kwargs.get('browser_session') is session
	assert session.browser_profile.allowed_domains == ['example.test']
	assert session.browser_profile.keep_alive is True


async def test_conflicting_domain_override_is_not_silently_ignored(setup_server):
	server, factory, _ = setup_server
	session = BrowserSession(allowed_domains=['example.test'])
	server.browser_session = session
	result = await server._execute_tool('retry_with_browser_use_agent', {'task': 'Continue', 'allowed_domains': ['other.test']})
	factory.assert_not_called()
	assert 'same_tab' in result
	assert session.browser_profile.allowed_domains == ['example.test']


async def test_retry_schema_advertises_session_reuse(setup_server):
	server, _, _ = setup_server
	handler = server.server.get_request_handler('tools/list')
	assert handler is not None
	result = await handler.handler(None, types.PaginatedRequestParams())
	tool = next(tool for tool in result.tools if tool.name == 'retry_with_browser_use_agent')
	assert tool.input_schema['properties']['same_tab']['default'] is True
