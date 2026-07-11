"""Regression tests: navigation readiness detection must actually detect page load.

cdp-use's event registry is single-slot per CDP method: registering a per-session
Page.lifecycleEvent closure replaces the previous one, so only the most recently
attached target recorded lifecycle events. Any earlier tab's event deque went silent,
and every navigation on it burned the full readiness timeout (3s same-domain /
8s cross-domain) before proceeding on a page in unknown load state.

Lifecycle events are now stored per-target in SessionManager, fed by one global
handler registered once on the root CDP client.
"""

import asyncio
import time

import pytest

from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

SIMPLE_HTML = '<html><head><title>fast page</title></head><body>hello</body></html>'

# Generous bound for a local page load: well above real load time (~100ms),
# well below the 3s that a readiness-timeout fallback burns.
FAST_NAVIGATION_BOUND_S = 2.5


@pytest.fixture
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	yield session
	await session.kill()


async def test_navigation_detects_readiness_without_burning_timeout(httpserver, browser_session: BrowserSession):
	"""A local page load must complete as soon as the load event fires, not after the fallback timeout."""
	httpserver.expect_request('/fast').respond_with_data(SIMPLE_HTML, content_type='text/html')

	start = time.monotonic()
	await browser_session.navigate_to(httpserver.url_for('/fast'))
	elapsed = time.monotonic() - start

	assert elapsed < FAST_NAVIGATION_BOUND_S, (
		f'navigation took {elapsed:.2f}s — readiness detection failed and the fallback timeout was burned'
	)


async def test_first_tab_navigation_still_works_after_second_tab_opens(httpserver, browser_session: BrowserSession):
	"""Opening a new tab must not disable lifecycle monitoring on existing tabs.

	Pre-fix: the second tab's per-session handler registration replaced the first
	tab's on the shared root client, freezing the first tab's event deque — every
	subsequent navigation on tab A hit the full readiness timeout.
	"""
	httpserver.expect_request('/a').respond_with_data(SIMPLE_HTML, content_type='text/html')
	httpserver.expect_request('/b').respond_with_data(SIMPLE_HTML, content_type='text/html')
	httpserver.expect_request('/a2').respond_with_data(SIMPLE_HTML, content_type='text/html')

	await browser_session.navigate_to(httpserver.url_for('/a'))
	tab_a = browser_session.agent_focus_target_id
	assert tab_a is not None

	# Open a second tab — its target attach re-runs page monitoring setup
	event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/b'), new_tab=True))
	await event
	await asyncio.sleep(0.5)

	# Navigate the FIRST tab again (same domain -> 3s fallback timeout pre-fix)
	start = time.monotonic()
	await browser_session._navigate_and_wait(httpserver.url_for('/a2'), tab_a, wait_until='load')
	elapsed = time.monotonic() - start

	assert elapsed < FAST_NAVIGATION_BOUND_S, (
		f'tab A navigation took {elapsed:.2f}s after tab B opened — its lifecycle monitoring was clobbered'
	)


async def test_readiness_timeout_is_reported_not_swallowed(httpserver, browser_session: BrowserSession):
	"""When readiness genuinely times out, _navigate_and_wait must say so instead of
	returning indistinguishably from success (NavigationCompleteEvent.loading_status
	exists for exactly this)."""

	def slow_image(request):
		time.sleep(5)
		from werkzeug.wrappers import Response

		return Response(b'', content_type='image/png')

	# DOMContentLoaded fires immediately; 'load' is held hostage by the stalled image.
	httpserver.expect_request('/hanging').respond_with_data(
		'<html><body><img src="/slow-img">never finishes loading</body></html>', content_type='text/html'
	)
	httpserver.expect_request('/slow-img').respond_with_handler(slow_image)

	target_id = browser_session.agent_focus_target_id
	assert target_id is not None

	status = await browser_session._navigate_and_wait(httpserver.url_for('/hanging'), target_id, timeout=1.0, wait_until='load')

	assert status is not None and 'timeout' in status, f'readiness timeout was swallowed, got status={status!r}'


async def test_successful_navigation_returns_no_timeout_status(httpserver, browser_session: BrowserSession):
	httpserver.expect_request('/ok').respond_with_data(SIMPLE_HTML, content_type='text/html')

	target_id = browser_session.agent_focus_target_id
	assert target_id is not None

	status = await browser_session._navigate_and_wait(httpserver.url_for('/ok'), target_id, wait_until='load')
	assert status is None


async def test_same_document_navigation_completes_immediately(httpserver, browser_session: BrowserSession):
	"""Fragment/History-API navigations must not burn the readiness timeout.

	Page.navigate returns no loaderId for same-document navigations and Chrome
	emits no new load/DOMContentLoaded lifecycle events for them — the navigation
	is already committed when Page.navigate returns.
	"""
	httpserver.expect_request('/page').respond_with_data(
		'<html><body><a id="anchor" name="section">s</a></body></html>', content_type='text/html'
	)

	await browser_session.navigate_to(httpserver.url_for('/page'))
	target_id = browser_session.agent_focus_target_id
	assert target_id is not None

	# Let the first load's trailing lifecycle events (networkIdle fires ~1s after
	# load) drain, so a stale event can't accidentally satisfy the fragment wait.
	await asyncio.sleep(1.5)

	start = time.monotonic()
	status = await browser_session._navigate_and_wait(httpserver.url_for('/page') + '#section', target_id, wait_until='load')
	elapsed = time.monotonic() - start

	assert elapsed < FAST_NAVIGATION_BOUND_S, f'same-document navigation took {elapsed:.2f}s — burned the readiness timeout'
	assert status is None, f'same-document navigation reported a bogus timeout: {status!r}'
