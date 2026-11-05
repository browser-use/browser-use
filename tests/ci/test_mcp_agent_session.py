"""MCP recovery uses real agents and sessions; only the LLM is scripted."""

import asyncio
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import mcp.types as types
import pytest

from browser_use.browser import BrowserSession
from browser_use.mcp import server as server_module
from browser_use.mcp.server import BrowserUseServer
from tests.ci.conftest import create_mock_llm


@pytest.fixture
def server():
	instance = BrowserUseServer()
	instance.config = {
		'llm': {'api_key': 'test-key'},
		'browser_profile': {'headless': True, 'user_data_dir': None, 'enable_default_extensions': False},
	}
	return instance


@pytest.mark.parametrize('tool', ['browser_close_session', 'browser_close_all'])
async def test_close_rejects_session_used_by_agent(server, tool):
	session = BrowserSession(keep_alive=True)
	server.browser_session = session
	server._track_session(session)
	server._agent_session = session
	try:
		result = await server._execute_tool(tool, {'session_id': session.id})
		assert 'running agent' in result
		assert session.id in server.active_sessions
		assert server.browser_session is session
	finally:
		server._agent_session = None
		await session.kill()


async def test_conflicting_domain_override_is_not_silently_ignored(server):
	session = BrowserSession(allowed_domains=['127.0.0.1'])
	server.browser_session = session
	result = await server._execute_tool('retry_with_browser_use_agent', {'task': 'Continue', 'allowed_domains': ['localhost']})
	assert 'same_tab' in result
	assert session.browser_profile.allowed_domains == ['127.0.0.1']


@pytest.mark.parametrize('has_tracked_peer', [False, True])
async def test_close_all_clears_untracked_current_session(server, has_tracked_peer):
	"""A failed initialization must not leave a stale current session after close-all."""
	session = BrowserSession()
	peer = BrowserSession()
	server.browser_session = session
	server.tools = server_module.Tools()
	if has_tracked_peer:
		server._track_session(peer)
	try:
		await server._execute_tool('browser_close_all', {})
		assert server.browser_session is None
		assert server.tools is None
		assert not server.active_sessions
	finally:
		await session.kill()
		await peer.kill()


async def test_retry_schema_advertises_session_reuse(server):
	handler = server.server.get_request_handler('tools/list')
	assert handler is not None
	result = await handler.handler(None, types.PaginatedRequestParams())
	tool = next(tool for tool in result.tools if tool.name == 'retry_with_browser_use_agent')
	assert tool.input_schema['properties']['same_tab']['default'] is True


@pytest.mark.integration
@pytest.mark.parametrize('fails', [False, True])
async def test_recovery_preserves_live_page_and_session(server, monkeypatch, mock_llm, httpserver, fails):
	"""Observe lifetime checks outside Agent.run(), where errors cannot swallow assertions."""
	httpserver.expect_request('/form').respond_with_data(
		'<html><body><input id="field" value="unfinished"></body></html>', content_type='text/html'
	)
	host = urlsplit(httpserver.url_for('/form')).hostname
	assert host is not None
	session = BrowserSession(
		headless=True, keep_alive=False, user_data_dir=None, enable_default_extensions=False, allowed_domains=[host]
	)
	server.browser_session = session
	server._track_session(session)
	observations = []
	original_invoke = mock_llm.ainvoke.side_effect

	async def respond(*args, **kwargs):
		server.active_sessions[session.id]['last_activity'] = 0
		await server._cleanup_expired_sessions()
		observations.append((session.browser_profile.keep_alive, session.id in server.active_sessions))
		if fails:
			raise RuntimeError('scripted model failure')
		return await original_invoke(*args, **kwargs)

	mock_llm.ainvoke.side_effect = respond
	monkeypatch.setattr(server_module, 'ChatOpenAI', lambda **kwargs: mock_llm)
	try:
		await session.start()
		await server._execute_tool('browser_navigate', {'url': httpserver.url_for('/form')})
		page = await session.get_current_page()
		assert page is not None
		await page.evaluate("() => { document.querySelector('#field').value = 'live-edit'; }")
		tabs = await session.get_tabs()
		result = await server._execute_tool(
			'retry_with_browser_use_agent', {'task': 'Finish the task on the current page', 'max_steps': 1, 'use_vision': False}
		)
		assert observations and all(keep_alive and tracked for keep_alive, tracked in observations)
		assert ('Success: True' in result) is not fails
		assert server.browser_session is session
		assert session.browser_profile.keep_alive is False
		assert session.browser_profile.allowed_domains == [host]
		assert server._agent_session is None
		assert len(await session.get_tabs()) == len(tabs)
		page = await session.get_current_page()
		assert page is not None
		assert 'live-edit' in await page.evaluate("() => document.querySelector('#field').value")
		# The event bus must still service a subsequent direct MCP command.
		await server._execute_tool('browser_navigate', {'url': httpserver.url_for('/form')})
		assert await session.get_current_page_url() == httpserver.url_for('/form')
	finally:
		await session.kill()


@pytest.mark.integration
@pytest.mark.parametrize('same_tab', [False, True])
async def test_recovery_without_a_session_uses_configured_profile(server, monkeypatch, mock_llm, same_tab):
	monkeypatch.setattr(server_module, 'ChatOpenAI', lambda **kwargs: mock_llm)
	result = await server._execute_tool(
		'retry_with_browser_use_agent', {'task': 'Finish now', 'same_tab': same_tab, 'max_steps': 1, 'use_vision': False}
	)
	assert 'Success: True' in result
	assert server.browser_session is None
	assert server._agent_session is None


@pytest.mark.integration
async def test_separate_recovery_leaves_active_session_untouched(server, monkeypatch, mock_llm, httpserver):
	httpserver.expect_request('/isolated').respond_with_data(
		'<html><body>Separate session</body></html>', content_type='text/html'
	)
	isolated_url = httpserver.url_for('/isolated')
	session = BrowserSession(headless=True, keep_alive=False, user_data_dir=None, enable_default_extensions=False)
	server.browser_session = session
	server._track_session(session)
	monkeypatch.setattr(server_module, 'ChatOpenAI', lambda **kwargs: mock_llm)
	try:
		await session.start()
		page = await session.get_current_page()
		assert page is not None
		await page.evaluate("() => { window.recoveryMarker = 'original-session'; }")
		result = await server._execute_tool(
			'retry_with_browser_use_agent',
			{'task': f'Visit {isolated_url} and finish', 'same_tab': False, 'max_steps': 1, 'use_vision': False},
		)
		assert 'Success: True' in result
		assert isolated_url in result
		assert server.browser_session is session
		assert session.browser_profile.keep_alive is False
		assert session.id in server.active_sessions
		assert await page.evaluate('() => window.recoveryMarker') == 'original-session'
	finally:
		await session.kill()


@pytest.mark.integration
async def test_concurrent_recovery_waits_for_previous_agent(server, monkeypatch):
	first_entered = asyncio.Event()
	release_first = asyncio.Event()
	second_started = asyncio.Event()
	created_models = []

	def create_llm(**kwargs):
		llm = create_mock_llm()
		is_first = not created_models
		created_models.append(llm)
		invoke = llm.ainvoke
		assert isinstance(invoke, AsyncMock)
		original_invoke = invoke.side_effect

		async def respond(*args, **kwargs):
			if is_first:
				first_entered.set()
				await release_first.wait()
			return await original_invoke(*args, **kwargs)

		invoke.side_effect = respond
		return llm

	monkeypatch.setattr(server_module, 'ChatOpenAI', create_llm)
	arguments = {'task': 'Finish now', 'max_steps': 1, 'use_vision': False}
	first = asyncio.create_task(server._execute_tool('retry_with_browser_use_agent', arguments))
	second = None
	try:
		await asyncio.wait_for(first_entered.wait(), timeout=30)

		async def start_second():
			second_started.set()
			return await server._execute_tool('retry_with_browser_use_agent', arguments)

		second = asyncio.create_task(start_second())
		await asyncio.wait_for(second_started.wait(), timeout=5)
		# start_second runs until it suspends on the real lock; a second model
		# would already have been constructed if dispatch were not serialized.
		assert len(created_models) == 1
		assert not second.done()
		release_first.set()
		results = await asyncio.wait_for(asyncio.gather(first, second), timeout=60)
		assert all('Success: True' in result for result in results)
		assert len(created_models) == 2
	finally:
		release_first.set()
		for task in (first, second):
			if task is not None and not task.done():
				task.cancel()
		await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)
