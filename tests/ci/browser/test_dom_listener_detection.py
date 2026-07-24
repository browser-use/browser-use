"""Regression tests for bounded JavaScript click-listener detection."""

import asyncio
from collections import Counter

import pytest

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
