"""Regression tests for bounded JavaScript click-listener detection."""

import asyncio
from collections import Counter

import pytest

from browser_use.agent.service import Agent
from browser_use.browser.events import BrowserStateRequestEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs import dom_watchdog
from browser_use.browser.watchdogs.dom_watchdog import DOMWatchdog
from browser_use.dom.service import _MAX_JS_CLICK_LISTENER_ELEMENTS, DomService


@pytest.fixture
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	yield session
	await session.kill()


async def test_listener_detection_preserves_small_pages_and_skips_cdp_fanout(httpserver, browser_session: BrowserSession):
	"""Direct listeners remain indexed normally, but listener-heavy pages do not flood CDP."""
	small_listener_count = 3
	overflow_listener_count = _MAX_JS_CLICK_LISTENER_ELEMENTS + 1

	def listener_page(element_count: int) -> str:
		elements = ''.join(f'<div id="custom-{index}">item {index}</div>' for index in range(element_count))
		return f"""
		<html>
			<body>
				{elements}
				<script>
					for (const element of document.querySelectorAll('[id^="custom-"]')) {{
						element.addEventListener('click', () => undefined);
					}}
				</script>
			</body>
		</html>
		"""

	httpserver.expect_request('/few-listeners').respond_with_data(listener_page(small_listener_count), content_type='text/html')
	httpserver.expect_request('/many-listeners').respond_with_data(
		listener_page(overflow_listener_count), content_type='text/html'
	)

	await browser_session.navigate_to(httpserver.url_for('/few-listeners'))
	cdp_session = await browser_session.get_or_create_cdp_session()
	cdp_calls: Counter[str] = Counter()
	original_send_raw = cdp_session.cdp_client.send_raw

	async def counted_send_raw(method, params=None, session_id=None):
		cdp_calls[method] += 1
		return await original_send_raw(method=method, params=params, session_id=session_id)

	cdp_session.cdp_client.send_raw = counted_send_raw

	small_state = await browser_session.get_browser_state_summary(include_screenshot=False)
	small_ids = {
		node.attributes.get('id')
		for node in small_state.dom_state.selector_map.values()
		if node.attributes.get('id', '').startswith('custom-')
	}
	assert small_ids == {f'custom-{index}' for index in range(small_listener_count)}
	assert cdp_calls['DOM.describeNode'] == small_listener_count

	await browser_session.navigate_to(httpserver.url_for('/many-listeners'))
	cdp_calls.clear()
	overflow_state = await browser_session.get_browser_state_summary(include_screenshot=False)

	assert overflow_state.dom_state is not None
	assert cdp_calls['DOM.describeNode'] == 0


async def test_ax_tree_failure_preserves_structural_dom(httpserver, browser_session: BrowserSession, monkeypatch):
	"""An unavailable accessibility tree must not erase the usable structural DOM."""
	httpserver.expect_request('/ax-unavailable').respond_with_data(
		'<html><body><button id="continue">Continue</button></body></html>',
		content_type='text/html',
	)

	async def fail_ax_tree(_service: DomService, _target_id):
		raise asyncio.CancelledError

	monkeypatch.setattr(DomService, '_get_ax_tree_for_all_frames', fail_ax_tree)
	await browser_session.navigate_to(httpserver.url_for('/ax-unavailable'))

	state = await browser_session.get_browser_state_summary(include_screenshot=False)

	assert state.dom_state is not None
	assert any(node.attributes.get('id') == 'continue' for node in state.dom_state.selector_map.values())


async def test_screenshot_timeout_preserves_structural_dom(httpserver, browser_session: BrowserSession, monkeypatch):
	"""A stalled state screenshot must not consume the outer event's recovery budget."""
	httpserver.expect_request('/screenshot-unavailable').respond_with_data(
		'<html><body><button id="continue">Continue</button></body></html>',
		content_type='text/html',
	)

	async def hang_screenshot(_watchdog: DOMWatchdog):
		await asyncio.Future()

	monkeypatch.setattr(DOMWatchdog, '_capture_clean_screenshot', hang_screenshot)
	monkeypatch.setattr(dom_watchdog, '_BROWSER_STATE_PARALLEL_TASK_BUDGET_SECONDS', 0.1)
	await browser_session.navigate_to(httpserver.url_for('/screenshot-unavailable'))

	state = await browser_session.get_browser_state_summary(include_screenshot=True)

	assert state.screenshot is None
	assert state.dom_state is not None
	assert any(node.attributes.get('id') == 'continue' for node in state.dom_state.selector_map.values())


async def test_whole_state_timeout_returns_model_visible_non_actionable_state(
	httpserver, browser_session: BrowserSession, monkeypatch
):
	"""A whole-state timeout must call the model without exposing earlier selectors."""
	httpserver.expect_request('/cached-state').respond_with_data(
		'<html><body><button id="continue">Continue</button></body></html>',
		content_type='text/html',
	)
	await browser_session.navigate_to(httpserver.url_for('/cached-state'))
	initial_state = await browser_session.get_browser_state_summary(include_screenshot=False)
	assert initial_state.dom_state.selector_map

	class TimedOutStateEvent:
		async def event_result(self, **_kwargs):
			raise TimeoutError

	original_dispatch = browser_session.event_bus.dispatch
	monkeypatch.setattr(
		browser_session.event_bus,
		'dispatch',
		lambda event: TimedOutStateEvent() if isinstance(event, BrowserStateRequestEvent) else original_dispatch(event),
	)

	state = await browser_session.get_browser_state_summary(include_screenshot=True)

	assert state.dom_state.selector_map == {}
	assert await browser_session.get_selector_map() == {}
	assert state.screenshot is None
	assert state.state_error is not None
	assert 'no element indices are safe to use' in state.state_error
	assert browser_session._cached_browser_state_summary is state


async def test_fresh_state_after_timeout_repopulates_selector_map(httpserver, browser_session: BrowserSession, monkeypatch):
	"""A timeout must not prevent the next successful state capture from rebuilding selectors."""
	httpserver.expect_request('/recover-state').respond_with_data(
		'<html><body><button id="continue">Continue</button></body></html>',
		content_type='text/html',
	)
	await browser_session.navigate_to(httpserver.url_for('/recover-state'))
	initial_state = await browser_session.get_browser_state_summary(include_screenshot=False)
	assert initial_state.dom_state.selector_map

	async def hang_dom_build(_watchdog: DOMWatchdog, _previous_state=None):
		await asyncio.Future()

	with monkeypatch.context() as timeout_patch:
		timeout_patch.setenv('TIMEOUT_BrowserStateRequestEvent', '0.1')
		timeout_patch.setattr(DOMWatchdog, '_build_dom_tree_without_highlights', hang_dom_build)
		timed_out_state = await browser_session.get_browser_state_summary(include_screenshot=False)

	assert timed_out_state.dom_state.selector_map == {}
	assert await browser_session.get_selector_map() == {}

	recovered_state = await browser_session.get_browser_state_summary(include_screenshot=False)
	recovered_nodes = recovered_state.dom_state.selector_map
	continue_index = next(index for index, node in recovered_nodes.items() if node.attributes.get('id') == 'continue')

	assert recovered_state.state_error is None
	assert await browser_session.get_element_by_index(continue_index) is recovered_nodes[continue_index]


async def test_initial_state_timeout_still_returns_model_visible_state(browser_session: BrowserSession, monkeypatch):
	"""The first state timeout must not require an earlier cached state."""

	class TimedOutStateEvent:
		async def event_result(self, **_kwargs):
			raise TimeoutError

	assert browser_session._cached_browser_state_summary is None
	monkeypatch.setattr(browser_session.event_bus, 'dispatch', lambda _event: TimedOutStateEvent())

	state = await browser_session.get_browser_state_summary(include_screenshot=True)

	assert state.dom_state.selector_map == {}
	assert state.screenshot is None
	assert state.state_error is not None
	assert state.url


async def test_agent_still_calls_model_after_state_timeout(browser_session: BrowserSession, mock_llm, monkeypatch):
	"""Returning the minimal state must let the normal model/action loop continue."""

	class TimedOutStateEvent:
		async def event_result(self, **_kwargs):
			raise TimeoutError

	original_dispatch = browser_session.event_bus.dispatch
	monkeypatch.setattr(
		browser_session.event_bus,
		'dispatch',
		lambda event: TimedOutStateEvent() if isinstance(event, BrowserStateRequestEvent) else original_dispatch(event),
	)
	model_call_count = 0
	original_ainvoke = mock_llm.ainvoke

	async def counted_ainvoke(*args, **kwargs):
		nonlocal model_call_count
		model_call_count += 1
		return await original_ainvoke(*args, **kwargs)

	monkeypatch.setattr(mock_llm, 'ainvoke', counted_ainvoke)
	agent = Agent(task='Finish after inspecting the available state.', llm=mock_llm, browser_session=browser_session)

	history = await agent.run(max_steps=1)

	assert model_call_count >= 1
	assert history.is_done() is True
