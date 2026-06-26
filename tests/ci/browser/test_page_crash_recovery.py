"""
Test automatic recovery from a page/tab renderer crash (issue #5067).

When the agent's focused tab crashes (renderer process gone), Chrome fires a
crash event (``Inspector.targetCrashed`` on the page session and/or
``Target.targetCrashed`` on the browser channel) but does NOT detach the
target — so the agent keeps focus on a dead page and would otherwise hang
reading its state. These tests verify that:

1. Both crash-event handlers record the focused tab's URL (and ignore
   background-tab crashes / duplicate events).
2. ``recover_from_page_crash()`` reloads the crashed page (reviving the
   renderer) and reports what it did.
3. It is a no-op (returns None) when no crash happened.
4. The agent surfaces the crash to the LLM via an injected long-term memory.

Note on triggering crashes: a real ``Page.crash`` and the subsequent renderer
revival are environment-dependent (headless Linux CI does not reliably emit the
crash events nor revive the renderer on reload). So these tests deliver the
crash event to the handler directly, exactly as Chrome's CDP dispatcher would,
which makes detection deterministic across platforms. Recovery (real
``navigate_to``) and the agent step run for real against a live browser.

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


def _focus_session_id(session: BrowserSession):
	"""A live CDP session id for the agent's focused target."""
	sessions = session.session_manager.get_all_sessions_for_target(session.agent_focus_target_id)
	assert sessions, 'no CDP session for the focused target'
	return sessions[0].session_id


def _simulate_focus_crash(session: BrowserSession) -> None:
	"""Deliver a renderer-crash event to the handler, as Chrome's CDP dispatcher
	would. We do not call ``Page.crash`` for real: actually crashing the renderer
	and reviving it via reload is environment-dependent and unreliable in headless
	CI. Detection is exercised here; the recovery path (real ``navigate_to``) and
	the agent step run for real against a live browser."""
	session._on_inspector_crashed_cdp({}, session_id=_focus_session_id(session))


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
	async def test_crash_handlers_record_focus_crash(self, browser_session, base_url):
		"""Both handlers record a focus-tab crash; background tabs + dupes are ignored."""
		await browser_session.navigate_to(f'{base_url}/page')
		focus_id = browser_session.agent_focus_target_id
		assert browser_session._crashed_focus_url is None

		# Inspector.targetCrashed (page-session event, identified by session_id)
		browser_session._on_inspector_crashed_cdp({}, session_id=_focus_session_id(browser_session))
		assert browser_session._crashed_focus_url is not None
		assert browser_session._crashed_focus_url.endswith('/page')
		assert browser_session._crashed_focus_target_id == focus_id

		# A duplicate event for the same target is a no-op (de-duplicated).
		browser_session._on_target_crashed_cdp({'targetId': focus_id, 'status': 'crashed', 'errorCode': 5})
		assert browser_session._crashed_focus_target_id == focus_id

		# A crash in a non-focused target is ignored.
		browser_session._crashed_focus_url = None
		browser_session._crashed_focus_target_id = None
		browser_session._on_target_crashed_cdp({'targetId': 'SOME_OTHER_TARGET', 'status': 'crashed', 'errorCode': 5})
		assert browser_session._crashed_focus_url is None

		# Target.targetCrashed (browser-channel event, carries targetId)
		browser_session._on_target_crashed_cdp({'targetId': focus_id, 'status': 'crashed', 'errorCode': 5})
		assert browser_session._crashed_focus_url is not None
		assert browser_session._crashed_focus_target_id == focus_id

	async def test_recover_reloads_after_crash(self, browser_session, base_url):
		"""recover_from_page_crash() reloads the crashed page and leaves it usable."""
		await browser_session.navigate_to(f'{base_url}/page')
		_simulate_focus_crash(browser_session)
		assert browser_session._crashed_focus_url is not None

		recovery = await asyncio.wait_for(browser_session.recover_from_page_crash(), timeout=20)

		assert isinstance(recovery, PageCrashRecovery)
		assert recovery.action == 'reloaded'
		assert recovery.crashed_url.endswith('/page')
		# Flag consumed so we don't recover twice.
		assert browser_session._crashed_focus_url is None
		assert browser_session._crashed_focus_target_id is None
		# Recovery navigated to the crashed URL and the page is loaded + responsive.
		assert await _eval(browser_session, 'document.title') == 'Crash Test'

	async def test_recover_blank_tab_crash_respawns(self, browser_session):
		"""A crash on a blank tab still navigates (respawns) rather than faking success."""
		# The initial focused tab is about:blank.
		assert browser_session._crashed_focus_url is None
		_simulate_focus_crash(browser_session)

		recovery = await asyncio.wait_for(browser_session.recover_from_page_crash(), timeout=20)

		assert isinstance(recovery, PageCrashRecovery)
		assert recovery.action == 'reloaded'  # a navigation to about:blank was issued
		# Renderer is responsive after recovery.
		assert await _eval(browser_session, '1 + 1') == 2

	async def test_recover_failed_reload_switches_off_dead_tab(self):
		"""If reload fails, focus must move to a fresh live tab (not the dead one),
		even when the crashed tab is blank (navigate_to(new_tab=True) would reuse it)."""
		# allowed_domains makes a reload of the crashed URL raise (blocked before any
		# network fetch), exercising the failure fallback deterministically.
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=True,
				allowed_domains=['example-allowed.test'],
			)
		)
		await session.start()
		try:
			dead_id = session.agent_focus_target_id  # initial about:blank tab
			# Pretend this tab crashed while showing a URL navigation will now reject.
			session._crashed_focus_target_id = dead_id
			session._crashed_focus_url = 'http://disallowed.invalid/page'

			recovery = await asyncio.wait_for(session.recover_from_page_crash(), timeout=20)

			assert isinstance(recovery, PageCrashRecovery)
			assert recovery.action == 'failed'
			# Focus moved to a genuinely different, live tab — not the dead one.
			assert session.agent_focus_target_id is not None
			assert session.agent_focus_target_id != dead_id
			assert session._crashed_focus_url is None  # cleared once focus left the dead tab
			assert await _eval(session, '1 + 1') == 2
		finally:
			await session.kill()

	async def test_recover_noop_without_crash(self, browser_session, base_url):
		"""recover_from_page_crash() returns None when nothing crashed, and a
		successful recovery is not repeated on the next call (markers cleared)."""
		await browser_session.navigate_to(f'{base_url}/page')
		assert await browser_session.recover_from_page_crash() is None

		_simulate_focus_crash(browser_session)
		assert (await browser_session.recover_from_page_crash()).action == 'reloaded'
		# Markers were cleared on success, so a second call is a no-op.
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
				_simulate_focus_crash(agent.browser_session)
				crash_state['done'] = True

		agent = Agent(task='Inspect the page', llm=llm, browser_session=browser_session)
		await asyncio.wait_for(agent.run(max_steps=1, on_step_start=on_step_start), timeout=90)

		assert crash_state['done'], 'tab was never crashed'
		# The crash flag was consumed by the recovery in step().
		assert browser_session._crashed_focus_url is None
		# The crash notice reached the LLM input.
		all_text = ' '.join(_message_text(m) for msgs in captured for m in msgs).lower()
		assert 'crashed' in all_text, 'crash recovery memory was not shown to the LLM'
