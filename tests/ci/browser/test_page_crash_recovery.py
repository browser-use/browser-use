"""
Test automatic recovery from a page/tab renderer crash (issue #5067).

When the agent's focused tab crashes (renderer process gone), Chrome fires
``Target.targetCrashed`` but does NOT detach the target — so the agent keeps
focus on a dead page and would otherwise hang reading its state. These tests
verify that:

1. The crash handler captures the focused tab's URL when it crashes.
2. ``recover_from_page_crash()`` reloads the crashed page (respawning the
   renderer) and reports what it did.
3. It is a no-op (returns None) when no crash happened.
4. The agent surfaces the crash to the LLM via an injected long-term memory.

Crashes are triggered with the CDP ``Page.crash`` method (the call itself never
returns because the renderer dies, so it is wrapped in a short timeout).

Usage:
	uv run pytest tests/ci/browser/test_page_crash_recovery.py -v -s
"""

import asyncio
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import PageCrashRecovery
from tests.ci.conftest import create_mock_llm


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/page').respond_with_data(
		'<html><head><title>Crash Test</title></head><body><h1>Crash Me</h1></body></html>',
		content_type='text/html',
	)
	server.expect_request('/other').respond_with_data(
		'<html><head><title>Other Page</title></head><body><h1>Other</h1></body></html>',
		content_type='text/html',
	)
	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True),
	)
	await session.start()
	yield session
	await session.kill()


async def _crash_focused_tab(session: BrowserSession) -> None:
	"""Crash the renderer of the agent's focused tab and wait for detection."""
	cdp = await session.get_or_create_cdp_session()
	try:
		# Page.crash never returns (renderer dies mid-call), so bound it.
		await asyncio.wait_for(cdp.cdp_client.send.Page.crash(session_id=cdp.session_id), timeout=2.0)
	except Exception:
		pass
	# Wait for the crash event (Inspector/Target.targetCrashed) to propagate.
	for _ in range(50):
		if session._crashed_focus_url:
			return
		await asyncio.sleep(0.1)


async def _eval(session: BrowserSession, expression: str):
	cdp = await session.get_or_create_cdp_session()
	res = await cdp.cdp_client.send.Runtime.evaluate(
		params={'expression': expression, 'returnByValue': True}, session_id=cdp.session_id
	)
	return res['result'].get('value')


def _message_text(msg) -> str:
	"""Flatten a BaseMessage's content (str or list of parts) into searchable text."""
	content = getattr(msg, 'content', '')
	if isinstance(content, str):
		return content
	if isinstance(content, list):
		return ' '.join(getattr(part, 'text', '') or '' for part in content)
	return str(content)


class TestPageCrashRecovery:
	async def test_crash_handler_captures_focused_url(self, browser_session, base_url):
		"""When the focused tab crashes, the handler records its target id + url."""
		await browser_session.navigate_to(f'{base_url}/page')

		assert browser_session._crashed_focus_url is None
		await _crash_focused_tab(browser_session)

		assert browser_session._crashed_focus_url is not None, 'targetCrashed was not detected'
		assert browser_session._crashed_focus_url.endswith('/page')
		assert browser_session._crashed_focus_target_id == browser_session.agent_focus_target_id

	async def test_recover_reloads_dead_renderer(self, browser_session, base_url):
		"""recover_from_page_crash() reloads the crashed page and revives the renderer."""
		await browser_session.navigate_to(f'{base_url}/page')
		await _crash_focused_tab(browser_session)
		assert browser_session._crashed_focus_url is not None

		recovery = await asyncio.wait_for(browser_session.recover_from_page_crash(), timeout=20)

		assert isinstance(recovery, PageCrashRecovery)
		assert recovery.action == 'reloaded'
		assert recovery.crashed_url.endswith('/page')
		# Flag consumed so we don't recover twice.
		assert browser_session._crashed_focus_url is None
		assert browser_session._crashed_focus_target_id is None
		# The renderer is alive again and the page reloaded.
		assert await _eval(browser_session, 'document.title') == 'Crash Test'

	async def test_recover_noop_without_crash(self, browser_session, base_url):
		"""recover_from_page_crash() returns None when nothing crashed."""
		await browser_session.navigate_to(f'{base_url}/page')
		assert await browser_session.recover_from_page_crash() is None

	async def test_agent_step_informs_llm_after_crash(self, browser_session, base_url):
		"""A crash between steps is reloaded and surfaced to the LLM as memory."""
		await browser_session.navigate_to(f'{base_url}/page')

		captured: list = []
		llm = create_mock_llm(actions=None)  # returns a single done action
		ainvoke_mock = cast(AsyncMock, llm.ainvoke)
		inner = ainvoke_mock.side_effect

		async def capture(*args, **kwargs):
			captured.append(args[0] if args else [])
			return await inner(*args, **kwargs)

		ainvoke_mock.side_effect = capture

		crash_state = {'done': False}

		async def on_step_start(agent):
			# Crash the focused tab right before the step reads browser state.
			if not crash_state['done']:
				await _crash_focused_tab(agent.browser_session)
				crash_state['done'] = True

		agent = Agent(task='Inspect the page', llm=llm, browser_session=browser_session)
		await asyncio.wait_for(agent.run(max_steps=1, on_step_start=on_step_start), timeout=90)

		assert crash_state['done'], 'tab was never crashed'
		# The crash flag was consumed by the recovery in step().
		assert browser_session._crashed_focus_url is None
		# The crash notice reached the LLM input.
		all_text = ' '.join(_message_text(m) for msgs in captured for m in msgs).lower()
		assert 'crashed' in all_text, 'crash recovery memory was not shown to the LLM'
