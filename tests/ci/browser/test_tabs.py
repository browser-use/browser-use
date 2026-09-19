"""
Test multi-tab operations: creation, switching, closing, and background tabs.

Tests verify that:
1. Agent can create multiple tabs (3) and switch between them
2. Agent can close tabs with vision=True
3. Agent can handle buttons that open new tabs in background
4. Agent can continue and call done() after each tab operation
5. Browser state doesn't timeout during background tab operations

All tests use:
- max_steps=5 to allow multiple tab operations
- 120s timeout to fail if test takes too long
- Mock LLM to verify agent can still make decisions after tab operations

Usage:
	uv run pytest tests/ci/browser/test_tabs.py -v -s
"""

import asyncio
import time
from typing import Any

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionModel
from browser_use.browser import BrowserSession
from browser_use.browser.events import SwitchTabEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools
from tests.ci.conftest import create_mock_llm


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server for tab tests."""
	server = HTTPServer()
	server.start()

	# Route 1: Home page
	server.expect_request('/home').respond_with_data(
		'<html><head><title>Home Page</title></head><body><h1>Home Page</h1><p>This is the home page</p></body></html>',
		content_type='text/html',
	)

	# Route 2: Page 1
	server.expect_request('/page1').respond_with_data(
		'<html><head><title>Page 1</title></head><body><h1>Page 1</h1><p>First test page</p></body></html>',
		content_type='text/html',
	)

	# Route 3: Page 2
	server.expect_request('/page2').respond_with_data(
		'<html><head><title>Page 2</title></head><body><h1>Page 2</h1><p>Second test page</p></body></html>',
		content_type='text/html',
	)

	# Route 4: Page 3
	server.expect_request('/page3').respond_with_data(
		'<html><head><title>Page 3</title></head><body><h1>Page 3</h1><p>Third test page</p></body></html>',
		content_type='text/html',
	)

	# Route 5: Background tab page - has a link that opens a new tab in the background
	server.expect_request('/background-tab-test').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Background Tab Test</title></head>
		<body style="padding: 20px; font-family: Arial;">
			<h1>Background Tab Test</h1>
			<p>Click the link below to open a new tab in the background:</p>
			<a href="/page3" target="_blank" id="open-tab-link">Open New Tab (link)</a>
			<br><br>
			<button id="open-tab-btn" onclick="window.open('/page3', '_blank'); document.getElementById('status').textContent='Tab opened!'">
				Open New Tab (button)
			</button>
			<p id="status" style="margin-top: 20px; color: green;"></p>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='function')
async def browser_session():
	"""Create a browser session for tab tests."""
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


class TestMultiTabOperations:
	"""Test multi-tab creation, switching, and closing."""

	async def test_create_and_switch_three_tabs(self, browser_session, base_url):
		"""Test that agent can create 3 tabs, switch between them, and call done().

		This test verifies that browser state is retrieved between each step.
		"""
		start_time = time.time()

		actions = [
			# Action 1: Navigate to home page
			f"""
			{{
				"thinking": "I'll start by navigating to the home page",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to home page",
				"next_goal": "Navigate to home page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/home",
							"new_tab": false
						}}
					}}
				]
			}}
			""",
			# Action 2: Open page1 in new tab
			f"""
			{{
				"thinking": "Now I'll open page 1 in a new tab",
				"evaluation_previous_goal": "Home page loaded",
				"memory": "Opening page 1 in new tab",
				"next_goal": "Open page 1 in new tab",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/page1",
							"new_tab": true
						}}
					}}
				]
			}}
			""",
			# Action 3: Open page2 in new tab
			f"""
			{{
				"thinking": "Now I'll open page 2 in a new tab",
				"evaluation_previous_goal": "Page 1 opened in new tab",
				"memory": "Opening page 2 in new tab",
				"next_goal": "Open page 2 in new tab",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/page2",
							"new_tab": true
						}}
					}}
				]
			}}
			""",
			# Action 4: Switch to first tab
			"""
			{
				"thinking": "Now I'll switch back to the first tab",
				"evaluation_previous_goal": "Page 2 opened in new tab",
				"memory": "Switching to first tab",
				"next_goal": "Switch to first tab",
				"action": [
					{
						"switch": {
							"tab_id": "0000"
						}
					}
				]
			}
			""",
			# Action 5: Done
			"""
			{
				"thinking": "I've successfully created 3 tabs and switched between them",
				"evaluation_previous_goal": "Switched to first tab",
				"memory": "All tabs created and switched",
				"next_goal": "Complete task",
				"action": [
					{
						"done": {
							"text": "Successfully created 3 tabs and switched between them",
							"success": true
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)

		agent = Agent(
			task=f'Navigate to {base_url}/home, then open {base_url}/page1 and {base_url}/page2 in new tabs, then switch back to the first tab',
			llm=mock_llm,
			browser_session=browser_session,
		)

		# Run with timeout - should complete within 2 minutes
		try:
			history = await asyncio.wait_for(agent.run(max_steps=5), timeout=120)
			elapsed = time.time() - start_time

			print(f'\n⏱️  Test completed in {elapsed:.2f} seconds')
			print(f'📊 Completed {len(history)} steps')

			# Verify each step has browser state
			for i, step in enumerate(history.history):
				assert step.state is not None, f'Step {i} should have browser state'
				assert step.state.url is not None, f'Step {i} should have URL in browser state'
				print(f'  Step {i + 1}: URL={step.state.url}, tabs={len(step.state.tabs) if step.state.tabs else 0}')

			assert len(history) >= 4, 'Agent should have completed at least 4 steps'

			# Verify we have 3 tabs open
			tabs = await browser_session.get_tabs()
			assert len(tabs) >= 3, f'Should have at least 3 tabs open, got {len(tabs)}'

			# Verify agent completed successfully
			final_result = history.final_result()
			assert final_result is not None, 'Agent should return a final result'
			assert 'Successfully' in final_result, 'Agent should report success'

			# Note: Test is fast (< 1s) because mock LLM returns instantly and pages are simple,
			# but browser state IS being retrieved correctly between steps as verified above
		except TimeoutError:
			pytest.fail('Test timed out after 2 minutes - agent hung during tab operations')

	async def test_close_tab_with_vision(self, browser_session, base_url):
		"""Test that agent can close a tab with vision=True and call done()."""

		actions = [
			# Action 1: Navigate to home page
			f"""
			{{
				"thinking": "I'll start by navigating to the home page",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to home page",
				"next_goal": "Navigate to home page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/home",
							"new_tab": false
						}}
					}}
				]
			}}
			""",
			# Action 2: Open page1 in new tab
			f"""
			{{
				"thinking": "Now I'll open page 1 in a new tab",
				"evaluation_previous_goal": "Home page loaded",
				"memory": "Opening page 1 in new tab",
				"next_goal": "Open page 1 in new tab",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/page1",
							"new_tab": true
						}}
					}}
				]
			}}
			""",
			# Action 3: Close the current tab
			"""
			{
				"thinking": "Now I'll close the current tab (page1)",
				"evaluation_previous_goal": "Page 1 opened in new tab",
				"memory": "Closing current tab",
				"next_goal": "Close current tab",
				"action": [
					{
						"close": {
							"tab_id": "0001"
						}
					}
				]
			}
			""",
			# Action 4: Done
			"""
			{
				"thinking": "I've successfully closed the tab",
				"evaluation_previous_goal": "Tab closed",
				"memory": "Tab closed successfully",
				"next_goal": "Complete task",
				"action": [
					{
						"done": {
							"text": "Successfully closed the tab",
							"success": true
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)

		agent = Agent(
			task=f'Navigate to {base_url}/home, then open {base_url}/page1 in a new tab, then close the page1 tab',
			llm=mock_llm,
			browser_session=browser_session,
			use_vision=True,  # Enable vision for this test
		)

		# Run with timeout - should complete within 2 minutes
		try:
			history = await asyncio.wait_for(agent.run(max_steps=5), timeout=120)
			assert len(history) >= 3, 'Agent should have completed at least 3 steps'

			# Verify agent completed successfully
			final_result = history.final_result()
			assert final_result is not None, 'Agent should return a final result'
			assert 'Successfully' in final_result, 'Agent should report success'
		except TimeoutError:
			pytest.fail('Test timed out after 2 minutes - agent hung during tab closing with vision')

	async def test_background_tab_open_no_timeout(self, browser_session, base_url):
		"""Test that browser state doesn't timeout when a new tab opens in the background."""
		start_time = time.time()

		actions = [
			# Action 1: Navigate to home page
			f"""
			{{
				"thinking": "I'll navigate to the home page first",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to home page",
				"next_goal": "Navigate to home page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/home",
							"new_tab": false
						}}
					}}
				]
			}}
			""",
			# Action 2: Open page1 in new background tab (stay on home page)
			f"""
			{{
				"thinking": "I'll open page1 in a new background tab",
				"evaluation_previous_goal": "Home page loaded",
				"memory": "Opening background tab",
				"next_goal": "Open background tab without switching to it",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/page1",
							"new_tab": true
						}}
					}}
				]
			}}
			""",
			# Action 3: Immediately check browser state after background tab opens
			"""
			{
				"thinking": "After opening background tab, browser state should still be accessible",
				"evaluation_previous_goal": "Background tab opened",
				"memory": "Verifying browser state works",
				"next_goal": "Complete task",
				"action": [
					{
						"done": {
							"text": "Successfully opened background tab, browser state remains accessible",
							"success": true
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)

		agent = Agent(
			task=f'Navigate to {base_url}/home and open {base_url}/page1 in a new tab',
			llm=mock_llm,
			browser_session=browser_session,
		)

		# Run with timeout - this tests if browser state times out when new tabs open
		try:
			history = await asyncio.wait_for(agent.run(max_steps=3), timeout=120)
			elapsed = time.time() - start_time

			print(f'\n⏱️  Test completed in {elapsed:.2f} seconds')
			print(f'📊 Completed {len(history)} steps')

			# Verify each step has browser state (the key test - no timeouts)
			for i, step in enumerate(history.history):
				assert step.state is not None, f'Step {i} should have browser state'
				assert step.state.url is not None, f'Step {i} should have URL in browser state'
				print(f'  Step {i + 1}: URL={step.state.url}, tabs={len(step.state.tabs) if step.state.tabs else 0}')

			assert len(history) >= 2, 'Agent should have completed at least 2 steps'

			# Verify agent completed successfully
			final_result = history.final_result()
			assert final_result is not None, 'Agent should return a final result'
			assert 'Successfully' in final_result, 'Agent should report success'

			# Verify we have at least 2 tabs
			tabs = await browser_session.get_tabs()
			print(f'  Final tab count: {len(tabs)}')
			assert len(tabs) >= 2, f'Should have at least 2 tabs after opening background tab, got {len(tabs)}'

		except TimeoutError:
			pytest.fail('Test timed out after 2 minutes - browser state timed out after opening background tab')

	async def test_rapid_tab_operations_no_timeout(self, browser_session, base_url):
		"""Test that browser state doesn't timeout during rapid tab operations."""

		actions = [
			# Action 1: Navigate to home page
			f"""
			{{
				"thinking": "I'll navigate to the home page",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to home page",
				"next_goal": "Navigate to home page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/home",
							"new_tab": false
						}}
					}}
				]
			}}
			""",
			# Action 2: Open page1 in new tab
			f"""
			{{
				"thinking": "Opening page1 in new tab",
				"evaluation_previous_goal": "Home page loaded",
				"memory": "Opening page1",
				"next_goal": "Open page1",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/page1",
							"new_tab": true
						}}
					}}
				]
			}}
			""",
			# Action 3: Open page2 in new tab
			f"""
			{{
				"thinking": "Opening page2 in new tab",
				"evaluation_previous_goal": "Page1 opened",
				"memory": "Opening page2",
				"next_goal": "Open page2",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/page2",
							"new_tab": true
						}}
					}}
				]
			}}
			""",
			# Action 4: Open page3 in new tab
			f"""
			{{
				"thinking": "Opening page3 in new tab",
				"evaluation_previous_goal": "Page2 opened",
				"memory": "Opening page3",
				"next_goal": "Open page3",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/page3",
							"new_tab": true
						}}
					}}
				]
			}}
			""",
			# Action 5: Verify browser state is still accessible
			"""
			{
				"thinking": "All tabs opened rapidly, browser state should still be accessible",
				"evaluation_previous_goal": "Page3 opened",
				"memory": "All tabs opened",
				"next_goal": "Complete task",
				"action": [
					{
						"done": {
							"text": "Successfully opened 4 tabs rapidly without timeout",
							"success": true
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)

		agent = Agent(
			task='Open multiple tabs rapidly and verify browser state remains accessible',
			llm=mock_llm,
			browser_session=browser_session,
		)

		# Run with timeout - should complete within 2 minutes
		try:
			history = await asyncio.wait_for(agent.run(max_steps=5), timeout=120)
			assert len(history) >= 4, 'Agent should have completed at least 4 steps'

			# Verify we have 4 tabs open
			tabs = await browser_session.get_tabs()
			assert len(tabs) >= 4, f'Should have at least 4 tabs open, got {len(tabs)}'

			# Verify agent completed successfully
			final_result = history.final_result()
			assert final_result is not None, 'Agent should return a final result'
			assert 'Successfully' in final_result, 'Agent should report success'
		except TimeoutError:
			pytest.fail('Test timed out after 2 minutes - browser state timed out during rapid tab operations')

	async def test_multiple_tab_switches_and_close(self, browser_session, base_url):
		"""Test that agent can switch between multiple tabs and close one."""

		actions = [
			# Action 1: Navigate to home page
			f"""
			{{
				"thinking": "I'll start by navigating to the home page",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to home page",
				"next_goal": "Navigate to home page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/home",
							"new_tab": false
						}}
					}}
				]
			}}
			""",
			# Action 2: Open page1 in new tab
			f"""
			{{
				"thinking": "Opening page 1 in new tab",
				"evaluation_previous_goal": "Home page loaded",
				"memory": "Opening page 1",
				"next_goal": "Open page 1",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/page1",
							"new_tab": true
						}}
					}}
				]
			}}
			""",
			# Action 3: Open page2 in new tab
			f"""
			{{
				"thinking": "Opening page 2 in new tab",
				"evaluation_previous_goal": "Page 1 opened",
				"memory": "Opening page 2",
				"next_goal": "Open page 2",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/page2",
							"new_tab": true
						}}
					}}
				]
			}}
			""",
			# Action 4: Switch to tab 1
			"""
			{
				"thinking": "Switching to tab 1 (page1)",
				"evaluation_previous_goal": "Page 2 opened",
				"memory": "Switching to page 1",
				"next_goal": "Switch to page 1",
				"action": [
					{
						"switch": {
							"tab_id": "0001"
						}
					}
				]
			}
			""",
			# Action 5: Close current tab
			"""
			{
				"thinking": "Closing the current tab (page1)",
				"evaluation_previous_goal": "Switched to page 1",
				"memory": "Closing page 1",
				"next_goal": "Close page 1",
				"action": [
					{
						"close": {
							"tab_id": "0001"
						}
					}
				]
			}
			""",
			# Action 6: Done
			"""
			{
				"thinking": "Successfully completed all tab operations",
				"evaluation_previous_goal": "Tab closed",
				"memory": "All operations completed",
				"next_goal": "Complete task",
				"action": [
					{
						"done": {
							"text": "Successfully created, switched, and closed tabs",
							"success": true
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)

		agent = Agent(
			task='Create 3 tabs, switch to the second one, then close it',
			llm=mock_llm,
			browser_session=browser_session,
		)

		# Run with timeout - should complete within 2 minutes
		try:
			history = await asyncio.wait_for(agent.run(max_steps=6), timeout=120)
			assert len(history) >= 5, 'Agent should have completed at least 5 steps'

			# Verify agent completed successfully
			final_result = history.final_result()
			assert final_result is not None, 'Agent should return a final result'
			assert 'Successfully' in final_result, 'Agent should report success'
		except TimeoutError:
			pytest.fail('Test timed out after 2 minutes - agent hung during multiple tab operations')


class _TabActionModel(ActionModel):
	"""ActionModel with explicit slots for the tab actions driven directly via tools.act().

	registry.create_action_model() builds its fields at runtime, so a statically declared
	subclass is what keeps pyright able to check these call sites. act() dispatches on the
	key returned by model_dump(exclude_unset=True), so the real registered actions still run.
	"""

	switch: dict[str, Any] | None = None
	navigate: dict[str, Any] | None = None
	click: dict[str, Any] | None = None


class TestSwitchTabFailureReporting:
	"""A failed `switch` must surface as ActionResult.error rather than a fake success.

	Previously both failure paths (a stale/unknown tab_id, and a missing SwitchTabEvent
	result) returned a non-error ActionResult claiming the switch succeeded. The false
	claim was written into long_term_memory, so subsequent steps reasoned from a tab the
	agent never actually reached.
	"""

	async def test_switch_to_nonexistent_tab_reports_error(self, browser_session):
		tools = Tools()

		tabs_before = await browser_session.get_tabs()
		live_ids = {tab.target_id[-4:] for tab in tabs_before}
		bogus_tab_id = 'zzzz'
		assert bogus_tab_id not in live_ids

		result = await tools.act(_TabActionModel(switch={'tab_id': bogus_tab_id}), browser_session=browser_session)

		assert result.error is not None, 'a failed tab switch must set ActionResult.error'
		assert bogus_tab_id in result.error
		assert 'Switched to tab' not in (result.extracted_content or '')
		assert 'Switched to tab' not in (result.long_term_memory or '')

		tabs_after = await browser_session.get_tabs()
		assert {tab.target_id[-4:] for tab in tabs_after} == live_ids, 'no tab switch should have happened'

	async def test_switch_to_open_tab_still_succeeds(self, browser_session, base_url):
		tools = Tools()

		original_tab_id = (await browser_session.get_tabs())[0].target_id[-4:]

		open_result = await tools.act(
			_TabActionModel(navigate={'url': f'{base_url}/page1', 'new_tab': True}),
			browser_session=browser_session,
		)
		assert open_result.error is None, f'opening a new tab should not error: {open_result.error}'

		result = await tools.act(_TabActionModel(switch={'tab_id': original_tab_id}), browser_session=browser_session)

		assert result.error is None, f'switching to a live tab must not error: {result.error}'
		assert result.long_term_memory is not None
		assert 'Switched to tab' in result.long_term_memory

	async def test_switch_reports_error_when_event_yields_no_result(self, browser_session, monkeypatch):
		"""A handler that completes without raising but yields no TargetID is still a failure.

		on_SwitchTabEvent returns a TargetID on every success path, so a missing result is
		never a quiet success - this must be reported as an error even though nothing raised.
		"""
		tools = Tools()
		tab_id = (await browser_session.get_tabs())[0].target_id[-4:]

		class NoResultEvent:
			async def _wait(self):
				return self

			def __await__(self):
				return self._wait().__await__()

			async def event_result(self, **_kwargs):
				return None

		original_dispatch = browser_session.event_bus.dispatch
		monkeypatch.setattr(
			browser_session.event_bus,
			'dispatch',
			lambda event: NoResultEvent() if isinstance(event, SwitchTabEvent) else original_dispatch(event),
		)

		result = await tools.act(_TabActionModel(switch={'tab_id': tab_id}), browser_session=browser_session)

		assert result.error is not None, 'a switch that yields no result must set ActionResult.error'
		assert 'produced no result' in result.error
		assert 'Switched to tab' not in (result.extracted_content or '')
		assert 'Switched to tab' not in (result.long_term_memory or '')


class TestAutomaticNewTabSwitchReporting:
	"""Automatic new-tab switching after a click must never claim success unless confirmed.

	Issue #5529: previously, _detect_new_tab_opened swallowed SwitchTabEvent failures
	via raise_if_any=False, and unconditionally reported "Automatically switched to new tab...".
	The truthful invariant is:
	1. If SwitchTabEvent succeeds and matches the new tab -> report "Automatically switched..."
	2. If SwitchTabEvent fails / raises an exception -> click remains successful (error=None),
	   but reports the truthful fallback "Note: This opened a new tab (tab_id: ...) - switch to it..."
	4. If SwitchTabEvent yields a mismatched target ID -> click remains successful, reports fallback note.
	"""

	@staticmethod
	def _synchronize_tab_creation_on_click(browser_session: BrowserSession, monkeypatch: pytest.MonkeyPatch) -> None:
		"""Harden tests against slow CI timing races in Chromium new-tab creation.

		When clicking an element that opens a new tab (<a target="_blank">), Chromium
		asynchronously creates the new target and dispatches Target.attachedToTarget to CDP.
		In production, _detect_new_tab_opened opportunistically checks for new tabs after a 50ms sleep.
		On slow CI runners, Chrome's target attachment can exceed 50ms, causing new_tabs to be empty.

		This helper wraps ClickElementEvent and ClickCoordinateEvent handlers so that after
		performing the real CDP click, the handler awaits until the new page target is registered
		in SessionManager before completing. This guarantees that _detect_new_tab_opened will always
		observe the newly created tab deterministically without modifying production code.
		"""
		for event_type in ('ClickElementEvent', 'ClickCoordinateEvent'):
			handlers = browser_session.event_bus.handlers.get(event_type, [])
			if handlers:
				orig_handler = handlers[0]

				async def wrapped_handler(event: Any, _orig: Any = orig_handler) -> Any:
					pre_targets = {t.target_id for t in browser_session.session_manager.get_all_page_targets()}
					result = await _orig(event)
					for _ in range(300):  # up to 3.0 seconds, polling every 10ms
						current_targets = browser_session.session_manager.get_all_page_targets()
						if any(t.target_id not in pre_targets for t in current_targets):
							break
						await asyncio.sleep(0.01)
					return result

				monkeypatch.setitem(browser_session.event_bus.handlers, event_type, [wrapped_handler])

	async def test_auto_switch_reports_success_when_event_succeeds(
		self, browser_session, base_url, monkeypatch: pytest.MonkeyPatch
	):
		tools = Tools()
		await tools.act(
			_TabActionModel(navigate={'url': f'{base_url}/background-tab-test'}),
			browser_session=browser_session,
		)
		state = await browser_session.get_browser_state_summary()
		link_idx = list(state.dom_state.selector_map.keys())[0]

		self._synchronize_tab_creation_on_click(browser_session, monkeypatch)

		result = await tools.act(
			_TabActionModel(click={'index': link_idx}),
			browser_session=browser_session,
		)

		assert result.error is None, f'click action must succeed: {result.error}'
		assert 'Automatically switched to new tab' in (result.extracted_content or '')
		assert 'Note: This opened a new tab' not in (result.extracted_content or '')

	@pytest.mark.parametrize(
		'switch_handler',
		[
			pytest.param(
				lambda event: (_ for _ in ()).throw(RuntimeError('CDP activateTarget failed')),
				id='handler_raises',
			),
			pytest.param(
				lambda event: None,
				id='no_result',
			),
			pytest.param(
				lambda event: 'bogus_different_target_id',
				id='mismatched_target',
			),
		],
	)
	async def test_auto_switch_reports_fallback_on_switch_failure(
		self, browser_session, base_url, monkeypatch: pytest.MonkeyPatch, switch_handler: Any
	):
		tools = Tools()
		await tools.act(
			_TabActionModel(navigate={'url': f'{base_url}/background-tab-test'}),
			browser_session=browser_session,
		)
		state = await browser_session.get_browser_state_summary()
		link_idx = list(state.dom_state.selector_map.keys())[0]

		self._synchronize_tab_creation_on_click(browser_session, monkeypatch)

		# Wrap switch_handler as an async coroutine function for bubus compatibility
		async def async_switch_handler(event: SwitchTabEvent):
			return switch_handler(event)

		monkeypatch.setitem(browser_session.event_bus.handlers, 'SwitchTabEvent', [async_switch_handler])

		result = await tools.act(
			_TabActionModel(click={'index': link_idx}),
			browser_session=browser_session,
		)

		assert result.error is None, 'click itself must succeed even when auto-switch fails'
		assert 'Automatically switched to new tab' not in (result.extracted_content or '')
		assert 'Note: This opened a new tab' in (result.extracted_content or '')
		assert 'switch to it if you need to interact with the new page' in (result.extracted_content or '')

	async def test_coordinate_click_auto_switch_fallback_when_event_handler_fails(
		self, browser_session, base_url, monkeypatch: pytest.MonkeyPatch
	):
		tools = Tools()
		tools.set_coordinate_clicking(True)
		await tools.act(
			_TabActionModel(navigate={'url': f'{base_url}/background-tab-test'}),
			browser_session=browser_session,
		)
		state = await browser_session.get_browser_state_summary()
		link_idx = list(state.dom_state.selector_map.keys())[0]
		node = await browser_session.get_element_by_index(link_idx)
		assert node is not None and node.snapshot_node and node.snapshot_node.bounds
		click_x = int(node.snapshot_node.bounds.x + node.snapshot_node.bounds.width / 2)
		click_y = int(node.snapshot_node.bounds.y + node.snapshot_node.bounds.height / 2)

		self._synchronize_tab_creation_on_click(browser_session, monkeypatch)

		async def failing_switch_handler(event: SwitchTabEvent):
			raise RuntimeError('CDP activateTarget failed')

		monkeypatch.setitem(browser_session.event_bus.handlers, 'SwitchTabEvent', [failing_switch_handler])

		result = await tools.act(
			_TabActionModel(click={'coordinate_x': click_x, 'coordinate_y': click_y}),
			browser_session=browser_session,
		)

		assert result.error is None, 'coordinate click must succeed even when auto-switch fails'
		assert 'Automatically switched to new tab' not in (result.extracted_content or '')
		assert 'Note: This opened a new tab' in (result.extracted_content or '')
		assert 'switch to it if you need to interact with the new page' in (result.extracted_content or '')
