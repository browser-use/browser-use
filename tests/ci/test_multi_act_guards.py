"""
Tests for multi_act() page-change guards.

Verifies:
1. Metadata: terminates_sequence flags are set correctly on built-in actions
2. Static guard: actions tagged terminates_sequence abort remaining queued actions
3. Runtime guard: URL/focus changes detected after click-on-link abort remaining actions
4. Safe chain: multiple inputs execute without interruption

Usage:
	uv run pytest tests/ci/test_multi_act_guards.py -v -s
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools
from tests.ci.conftest import create_mock_llm

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def http_server():
	"""Test HTTP server with pages for guard tests."""
	server = HTTPServer()
	server.start()

	server.expect_request('/form').respond_with_data(
		"""<html><head><title>Form Page</title></head><body>
		<h1>Form</h1>
		<input id="field1" type="text" placeholder="Field 1" />
		<input id="field2" type="text" placeholder="Field 2" />
		<input id="field3" type="text" placeholder="Field 3" />
		<button id="submit" type="submit">Submit</button>
		</body></html>""",
		content_type='text/html',
	)

	server.expect_request('/page_a').respond_with_data(
		"""<html><head><title>Page A</title></head><body>
		<h1>Page A</h1>
		<a id="link_b" href="/page_b">Go to Page B</a>
		</body></html>""",
		content_type='text/html',
	)

	server.expect_request('/page_b').respond_with_data(
		"""<html><head><title>Page B</title></head><body>
		<h1>Page B</h1>
		<p>You arrived at Page B</p>
		</body></html>""",
		content_type='text/html',
	)

	server.expect_request('/static').respond_with_data(
		"""<html><head><title>Static Page</title></head><body>
		<h1>Static</h1>
		<p>Nothing changes here</p>
		<input id="safe_input" type="text" />
		</body></html>""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await session.start()
	yield session
	await session.kill()
	await session.event_bus.stop(clear=True, timeout=5)


@pytest.fixture(scope='function')
def tools():
	return Tools()


# ---------------------------------------------------------------------------
# 1. Metadata tests — verify terminates_sequence flags
# ---------------------------------------------------------------------------


class TestTerminatesSequenceMetadata:
	"""Verify that built-in actions have correct terminates_sequence flags."""

	def test_navigate_terminates(self, tools):
		action = tools.registry.registry.actions.get('navigate')
		assert action is not None
		assert action.terminates_sequence is True

	def test_search_terminates(self, tools):
		action = tools.registry.registry.actions.get('search')
		assert action is not None
		assert action.terminates_sequence is True

	def test_go_back_terminates(self, tools):
		action = tools.registry.registry.actions.get('go_back')
		assert action is not None
		assert action.terminates_sequence is True

	def test_switch_terminates(self, tools):
		action = tools.registry.registry.actions.get('switch')
		assert action is not None
		assert action.terminates_sequence is True

	def test_click_does_not_terminate(self, tools):
		action = tools.registry.registry.actions.get('click')
		assert action is not None
		assert action.terminates_sequence is False

	def test_input_does_not_terminate(self, tools):
		action = tools.registry.registry.actions.get('input')
		assert action is not None
		assert action.terminates_sequence is False

	def test_scroll_does_not_terminate(self, tools):
		action = tools.registry.registry.actions.get('scroll')
		assert action is not None
		assert action.terminates_sequence is False

	def test_extract_does_not_terminate(self, tools):
		action = tools.registry.registry.actions.get('extract')
		assert action is not None
		assert action.terminates_sequence is False


# ---------------------------------------------------------------------------
# 2. Static guard — navigate as non-last action skips remaining
# ---------------------------------------------------------------------------


class TestStaticGuard:
	"""Verify that terminates_sequence actions abort the remaining queue."""

	async def test_navigate_aborts_remaining_actions(self, browser_session, base_url, tools):
		"""When navigate is action 2/3, action 3 should never execute."""
		# Start on a known page
		await tools.navigate(url=f'{base_url}/static', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		# Build action models: [scroll_down, navigate_to_page_a, scroll_down]
		ActionModel = tools.registry.create_action_model()
		actions = [
			ActionModel.model_validate({'scroll': {'down': True, 'pages': 1}}),
			ActionModel.model_validate({'navigate': {'url': f'{base_url}/page_a'}}),
			ActionModel.model_validate({'scroll': {'down': True, 'pages': 1}}),
		]

		mock_llm = create_mock_llm()
		agent = Agent(task='test', llm=mock_llm, browser_session=browser_session, tools=tools)

		results = await agent.multi_act(actions)

		# Should have executed exactly 2 actions (scroll + navigate), third skipped
		assert len(results) == 2, f'Expected 2 results but got {len(results)}: {results}'

		# Verify we actually navigated
		url = await browser_session.get_current_page_url()
		assert '/page_a' in url

	async def test_go_back_aborts_remaining_actions(self, browser_session, base_url, tools):
		"""go_back should abort remaining queued actions."""
		# Navigate to page_a then page_b so go_back has somewhere to go
		await tools.navigate(url=f'{base_url}/page_a', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await tools.navigate(url=f'{base_url}/page_b', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)

		ActionModel = tools.registry.create_action_model()
		actions = [
			ActionModel.model_validate({'go_back': {}}),
			ActionModel.model_validate({'scroll': {'down': True, 'pages': 1}}),
		]

		mock_llm = create_mock_llm()
		agent = Agent(task='test', llm=mock_llm, browser_session=browser_session, tools=tools)

		results = await agent.multi_act(actions)

		# go_back should terminate the sequence — only 1 result
		assert len(results) == 1, f'Expected 1 result but got {len(results)}: {results}'


# ---------------------------------------------------------------------------
# 3. Runtime guard — click on link changes URL, remaining actions skipped
# ---------------------------------------------------------------------------


class TestRuntimeGuard:
	"""Verify that URL/focus changes detected at runtime abort remaining actions."""

	async def test_click_link_aborts_remaining(self, browser_session, base_url, tools):
		"""Click a link that navigates to another page — remaining actions skipped."""
		await tools.navigate(url=f'{base_url}/page_a', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		# Get the selector map to find the link index
		state = await browser_session.get_browser_state_summary()
		assert state.dom_state is not None
		selector_map = state.dom_state.selector_map

		# Find the link element (a#link_b)
		link_index = None
		for idx, element in selector_map.items():
			if hasattr(element, 'tag_name') and element.tag_name == 'a':
				link_index = idx
				break

		assert link_index is not None, 'Could not find link element in selector map'

		ActionModel = tools.registry.create_action_model()
		actions = [
			ActionModel.model_validate({'click': {'index': link_index}}),
			ActionModel.model_validate({'scroll': {'down': True, 'pages': 1}}),
			ActionModel.model_validate({'scroll': {'down': True, 'pages': 1}}),
		]

		mock_llm = create_mock_llm()
		agent = Agent(task='test', llm=mock_llm, browser_session=browser_session, tools=tools)

		results = await agent.multi_act(actions)

		# Click navigated to page_b — runtime guard should stop at 1
		assert len(results) == 1, f'Expected 1 result but got {len(results)}: {results}'

		# Verify we're on page_b
		url = await browser_session.get_current_page_url()
		assert '/page_b' in url


# ---------------------------------------------------------------------------
# 4. Safe chain — multiple non-page-changing actions all execute
# ---------------------------------------------------------------------------


class TestSafeChain:
	"""Verify that non-page-changing actions execute without interruption."""

	async def test_multiple_scrolls_all_execute(self, browser_session, base_url, tools):
		"""Multiple scroll actions should all execute."""
		await tools.navigate(url=f'{base_url}/static', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		ActionModel = tools.registry.create_action_model()
		actions = [
			ActionModel.model_validate({'scroll': {'down': True, 'pages': 0.5}}),
			ActionModel.model_validate({'scroll': {'down': True, 'pages': 0.5}}),
			ActionModel.model_validate({'scroll': {'down': False, 'pages': 0.5}}),
		]

		mock_llm = create_mock_llm()
		agent = Agent(task='test', llm=mock_llm, browser_session=browser_session, tools=tools)

		results = await agent.multi_act(actions)

		# All 3 scrolls should execute
		assert len(results) == 3, f'Expected 3 results but got {len(results)}: {results}'
		# None should have errors
		for r in results:
			assert r.error is None, f'Unexpected error: {r.error}'
