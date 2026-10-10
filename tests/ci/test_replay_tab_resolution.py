"""Replayed tab actions must re-resolve their recorded tab id instead of replaying it verbatim.

A recorded `switch`/`close` carries only the last four characters of a CDP TargetID. A browser
started for the replay assigns TargetIDs afresh, so the recorded id can never resolve, and the
action used to fail into whatever page happened to be focused - leaving the remaining steps to act
on the wrong page. These tests cover the re-resolution by URL/title, the explicit failure when
nothing matches, and the removal of the false success that `close` used to report.
"""

from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from browser_use.agent.service import Agent, ReplayTabUnavailableError, match_replay_tab
from browser_use.agent.views import ActionModel, ActionResult, AgentHistory, AgentHistoryList, StepMetadata
from browser_use.browser import BrowserSession
from browser_use.browser.views import BrowserStateHistory, BrowserStateSummary, TabInfo
from browser_use.dom.serializer.serializer import SerializedDOMState
from browser_use.tools.service import Tools
from tests.ci.conftest import create_mock_llm


def _stub_live_tabs(agent, live_tabs: list[TabInfo]) -> None:
	"""Make the agent's browser report `live_tabs` as the tabs that exist now.

	BrowserSession validates assignment, so the stubs have to be placed with object.__setattr__.
	The state summary is stubbed alongside because these tests exercise tab re-resolution, not DOM
	capture; with no selector map every element action passes through untouched.
	"""
	object.__setattr__(agent.browser_session, 'get_tabs', AsyncMock(return_value=live_tabs))
	summary = BrowserStateSummary(
		dom_state=SerializedDOMState(_root=None, selector_map={}),
		url=live_tabs[0].url if live_tabs else 'about:blank',
		title=live_tabs[0].title if live_tabs else '',
		tabs=live_tabs,
	)
	object.__setattr__(agent.browser_session, 'get_browser_state_summary', AsyncMock(return_value=summary))


def _tab(tab_id: str, url: str, title: str = '') -> TabInfo:
	return TabInfo(url=url, title=title, target_id=tab_id)


class TestMatchReplayTab:
	"""`match_replay_tab` picks the live tab a recorded action meant, or nothing at all."""

	def test_exact_url_wins_over_a_reused_short_id(self):
		"""A different tab that happens to carry the recorded short id must not win.

		TargetID suffixes are re-issued, so id equality proves nothing. The recorded URL is the
		identifying fact; matching on the id first would switch to an unrelated page.
		"""
		recorded = _tab('D338', 'https://app.example/#/', 'Teller console')
		live = [
			_tab('D338', 'https://app.example/legacy/#/', 'BankVue'),  # same suffix, different page
			_tab('91AB', 'https://app.example/#/', 'Teller console'),  # same page, new id
		]

		matched = match_replay_tab(recorded, live)

		assert matched is not None
		assert matched.target_id == '91AB', 'must follow the URL, not the recycled id'

	def test_title_matches_when_the_url_moved_on(self):
		"""An SPA that changed its route still matches by title, which the id cannot do."""
		recorded = _tab('D338', 'https://app.example/#/home', 'Teller console')
		live = [_tab('91AB', 'https://app.example/#/home/transfer/000450.htm', 'Teller console')]

		matched = match_replay_tab(recorded, live)

		assert matched is not None
		assert matched.target_id == '91AB'

	def test_url_prefix_matches_a_deepened_route(self):
		"""A page that navigated deeper on the same origin is still the tab that was meant."""
		recorded = _tab('D338', 'https://app.example/#/')
		live = [_tab('91AB', 'https://app.example/#/home/transfer/000450.htm')]

		matched = match_replay_tab(recorded, live)

		assert matched is not None
		assert matched.target_id == '91AB'

	def test_short_id_is_the_last_resort(self):
		"""When URL and title are both unavailable the recorded id is still better than nothing."""
		recorded = _tab('D338', '', '')
		live = [_tab('91AB', 'https://example.com')]

		assert match_replay_tab(recorded, live) is None, 'no signal at all must not guess'

		live_with_suffix = [_tab('D338', 'https://example.com')]
		assert match_replay_tab(recorded, live_with_suffix) is not None

	def test_no_match_returns_none(self):
		"""Nothing resembling the recorded tab means the caller must fail, not pick arbitrarily."""
		recorded = _tab('D338', 'https://app.example/#/', 'Teller console')
		live = [_tab('91AB', 'https://other.example/', 'Other')]

		assert match_replay_tab(recorded, live) is None

	def test_missing_recorded_tab_or_empty_live_list_returns_none(self):
		"""Old history files without a tab entry, and a browser with no tabs, cannot resolve."""
		assert match_replay_tab(None, [_tab('91AB', 'https://x/')]) is None
		assert match_replay_tab(_tab('D338', 'https://x/'), []) is None

	def test_unknown_title_does_not_match(self):
		"""'Unknown title' is a placeholder, not an identifier; matching it would be a coin toss."""
		recorded = _tab('D338', '', 'Unknown title')
		live = [_tab('91AB', 'https://example.com', 'Unknown title')]

		assert match_replay_tab(recorded, live) is None


class TestRecordedTabLookup:
	"""The recorded tab entry is found in the step's own tab list, by its short id."""

	def test_recorded_tab_is_found_by_short_id(self):
		agent = Agent(task='t', llm=create_mock_llm())
		item = AgentHistory(
			model_output=None,
			result=[],
			state=BrowserStateHistory(
				url='https://app.example/#/',
				title='Teller console',
				tabs=[_tab('9418', 'https://shell.example/html/taskbar.html'), _tab('D338', 'https://app.example/#/')],
				interacted_element=[None],
			),
		)

		found = agent._recorded_tab(item, 'D338')

		assert found is not None
		assert found.url == 'https://app.example/#/'
		assert agent._recorded_tab(item, 'zzzz') is None
		assert agent._describe_live_tabs([_tab('91AB', 'https://app.example/#/')]) == '#91AB https://app.example/#/'
		assert agent._describe_live_tabs([]) == 'none'


class TestReplayTabReResolution:
	"""`_execute_history_step` rewrites a stale tab id, and fails loudly when it cannot."""

	@pytest.fixture
	def agent_with_tabs(self):
		"""(agent, recorded step, live tabs) with a browser whose tabs the test controls."""
		agent = Agent(task='t', llm=create_mock_llm())
		recorded_tabs = [
			_tab('9418', 'https://shell.example/html/taskbar.html', 'In-page taskbar'),
			_tab('D338', 'https://app.example/#/', 'Teller console'),
		]
		step = AgentHistory(
			model_output=agent.AgentOutput(
				evaluation_previous_goal=None,
				memory='switch to the app tab',
				next_goal=None,
				action=[{'switch': {'tab_id': 'D338'}}],  # type: ignore[arg-type]
			),
			result=[ActionResult(long_term_memory='Switched to tab #D338')],
			state=BrowserStateHistory(
				url='https://shell.example/html/taskbar.html',
				title='In-page taskbar',
				tabs=recorded_tabs,
				interacted_element=[None],
			),
			metadata=StepMetadata(step_start_time=0, step_end_time=1, step_number=1, step_interval=0.0),
		)
		return agent, step

	async def test_stale_tab_id_is_rewritten_to_the_live_tab(self, agent_with_tabs, monkeypatch):
		"""The same page under a new id is addressed by the new id, not by the recorded one."""
		agent, step = agent_with_tabs
		live_tabs = [
			_tab('9418', 'https://shell.example/html/taskbar.html', 'In-page taskbar'),
			_tab('91AB', 'https://app.example/#/', 'Teller console'),
		]
		_stub_live_tabs(agent, live_tabs)
		executed: list[dict] = []

		async def fake_multi_act(actions):
			executed.append(actions[0].model_dump(exclude_unset=True))
			return [ActionResult(long_term_memory='Switched to tab #91AB')]

		monkeypatch.setattr(agent, 'multi_act', fake_multi_act)

		results = await agent._execute_history_step(step, delay=0.0)

		assert executed, 'the step must still execute'
		assert executed[0]['switch']['tab_id'] == '91AB', 'the action must carry the live tab id'
		assert results[0].error is None

	async def test_unresolvable_tab_id_raises_before_executing_anything(self, agent_with_tabs, monkeypatch):
		"""No matching tab must stop the step, so later steps never run against the wrong page."""
		agent, step = agent_with_tabs
		_stub_live_tabs(agent, [_tab('91AB', 'https://elsewhere.example/', 'Other')])
		executed: list[dict] = []

		async def fake_multi_act(actions):
			executed.append(actions[0].model_dump(exclude_unset=True))
			return [ActionResult()]

		monkeypatch.setattr(agent, 'multi_act', fake_multi_act)

		with pytest.raises(ReplayTabUnavailableError) as raised:
			await agent._execute_history_step(step, delay=0.0)

		assert 'D338' in str(raised.value)
		assert not executed, 'a failed re-resolution must not dispatch the action at all'

	async def test_close_step_is_re_resolved_too(self, agent_with_tabs, monkeypatch):
		"""`close` carries the same ephemeral id and must be re-resolved the same way."""
		agent, step = agent_with_tabs
		step.model_output.action = [step.model_output.action[0].__class__.model_validate({'close': {'tab_id': 'D338'}})]
		_stub_live_tabs(agent, [_tab('91AB', 'https://app.example/#/', 'Teller console')])
		executed: list[dict] = []

		async def fake_multi_act(actions):
			executed.append(actions[0].model_dump(exclude_unset=True))
			return [ActionResult(long_term_memory='Closed tab #91AB')]

		monkeypatch.setattr(agent, 'multi_act', fake_multi_act)

		await agent._execute_history_step(step, delay=0.0)

		assert executed[0]['close']['tab_id'] == '91AB'


class TestReplayStopsOnUnresolvableTab:
	"""A stale tab is a deterministic failure, so the rerun must not retry it away."""

	async def test_rerun_raises_without_retrying_the_stale_tab(self, monkeypatch):
		# rerun_history starts the browser session before its loop; stub that so this test stays
		# hermetic and the assertion below is about the retry policy, not about CDP.
		agent = Agent(task='t', llm=create_mock_llm())
		step = AgentHistory(
			model_output=agent.AgentOutput(
				evaluation_previous_goal=None,
				memory='switch to a tab that is gone',
				next_goal=None,
				action=[{'switch': {'tab_id': 'D338'}}],  # type: ignore[arg-type]
			),
			result=[ActionResult(long_term_memory='Switched to tab #D338')],
			state=BrowserStateHistory(
				url='https://shell.example/html/taskbar.html',
				title='In-page taskbar',
				tabs=[_tab('D338', 'https://app.example/#/', 'Teller console')],
				interacted_element=[None],
			),
			metadata=StepMetadata(step_start_time=0, step_end_time=1, step_number=1, step_interval=0.0),
		)
		_stub_live_tabs(agent, [_tab('91AB', 'https://elsewhere.example/', 'Other')])
		object.__setattr__(agent.browser_session, 'start', AsyncMock())
		attempts = 0

		async def counting_step(*_args, **_kwargs):
			nonlocal attempts
			attempts += 1
			raise ReplayTabUnavailableError('Recorded tab #D338 no longer exists')

		monkeypatch.setattr(agent, '_execute_history_step', counting_step)

		with pytest.raises(RuntimeError, match='D338'):
			await agent.rerun_history(AgentHistoryList(history=[step]), skip_failures=False, max_retries=3)

		assert attempts == 1, 'a stale tab cannot appear by waiting, so it must not be retried'


class _TabActionModel(ActionModel):
	"""Explicit slots for the tab actions driven directly through tools.act()."""

	switch: dict[str, Any] | None = None
	close: dict[str, Any] | None = None


class TestCloseTabReportsFailure:
	"""`close` must not claim success when no tab matched its id."""

	async def test_close_on_an_unknown_tab_reports_an_error(self):
		"""A tab id that resolves to nothing must come back as an error, not as "closed".

		Reporting "closed (was already closed or invalid)" made a wrong tab id look like a completed
		step, so a replay kept going and its later steps acted on whatever page was still focused.
		"""

		class StubSession:
			"""Only the surface the close action touches before resolving the tab id."""

			active_modal_dialog_state = None
			cdp_client = None
			agent_focus_target_id = None

			async def get_target_id_from_tab_id(self, tab_id: str) -> str:
				raise ValueError(f'No TargetID found ending in tab_id=...{tab_id}')

		result = await Tools().act(_TabActionModel(close={'tab_id': 'zzzz'}), browser_session=cast(BrowserSession, StubSession()))

		assert result.error is not None, 'closing a tab that does not exist is not a success'
		assert 'zzzz' in result.error
		assert result.extracted_content is None
