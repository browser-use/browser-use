"""Regression tests for per-task timeouts in DOMWatchdog.on_BrowserStateRequestEvent.

Covers issue #4579: DOM build and clean-screenshot tasks were awaited without a
per-task cap. A remote browser with a silent half-dead WebSocket could keep
either task awaiting forever, blocking the handler for the full 30s event
budget. TimeoutWrappedCDPClient caps individual CDP calls (default 60s), but a
single DOM build is many sequential CDP calls, so the aggregate can still blow
the event-bus budget — the gap closed here.

The fix wraps each await with asyncio.wait_for using a configurable per-task
cap (BROWSER_USE_DOM_BUILD_TIMEOUT_S / BROWSER_USE_SCREENSHOT_TIMEOUT_S).
"""

from __future__ import annotations

import asyncio
import time

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs import dom_watchdog as dom_watchdog_module
from browser_use.browser.watchdogs.dom_watchdog import (
	_DOM_BUILD_TIMEOUT_FALLBACK_S,
	_SCREENSHOT_TIMEOUT_FALLBACK_S,
	_parse_env_task_timeout,
)
from browser_use.dom.views import SerializedDOMState

# ---------------------------------------------------------------------------
# _parse_env_task_timeout — pure unit tests, no browser
# ---------------------------------------------------------------------------


def test_parse_env_timeout_unset_returns_fallback(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.delenv('TEST_TIMEOUT_VAR', raising=False)
	assert _parse_env_task_timeout('TEST_TIMEOUT_VAR', 12.5) == 12.5


def test_parse_env_timeout_empty_string_returns_fallback(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('TEST_TIMEOUT_VAR', '')
	assert _parse_env_task_timeout('TEST_TIMEOUT_VAR', 12.5) == 12.5


def test_parse_env_timeout_valid_value_is_used(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('TEST_TIMEOUT_VAR', '30.5')
	assert _parse_env_task_timeout('TEST_TIMEOUT_VAR', 12.5) == 30.5


def test_parse_env_timeout_rejects_malformed_values(monkeypatch: pytest.MonkeyPatch):
	"""Mirrors the guard on BROWSER_USE_CDP_TIMEOUT_S — a bad env value would
	otherwise time out every state request immediately (nan / 0) or never
	(inf / negative)."""
	for bad in ('nan', 'NaN', 'inf', '-inf', '0', '0.0', '-5', '-0.01', 'abc'):
		monkeypatch.setenv('TEST_TIMEOUT_VAR', bad)
		assert _parse_env_task_timeout('TEST_TIMEOUT_VAR', 7.0) == 7.0, f'Expected fallback for {bad!r}'


def test_parse_env_timeout_accepts_small_positive(monkeypatch: pytest.MonkeyPatch):
	"""Small but finite positive values should pass — used by tests that
	want to force fast timeouts."""
	monkeypatch.setenv('TEST_TIMEOUT_VAR', '0.001')
	assert _parse_env_task_timeout('TEST_TIMEOUT_VAR', 10.0) == 0.001


def test_default_timeouts_are_sensible():
	"""DOM build needs more headroom than screenshot (many CDP calls vs one),
	and both must stay well below the 30s BrowserStateRequestEvent budget so
	the timeout fires before the event-level kill — otherwise the per-task
	cap adds nothing over what the event bus already enforces."""
	assert 0 < _SCREENSHOT_TIMEOUT_FALLBACK_S < _DOM_BUILD_TIMEOUT_FALLBACK_S
	assert _DOM_BUILD_TIMEOUT_FALLBACK_S < 30.0


# ---------------------------------------------------------------------------
# Integration — real BrowserSession + pytest-httpserver
#
# We inject a hang into the watchdog's per-component methods (the inner CDP
# calls), not into the session itself. The handler under test is real, the
# event bus is real, the browser is real. Only the leaf coroutine that
# normally fans out into CDP traffic is swapped for one that awaits an
# event we can release — which is the precise shape of a stale-WebSocket
# hang the issue describes.
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def http_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/page').respond_with_data(
		'<!doctype html><html><head><title>T</title></head>'
		'<body><h1 id="h">Hello</h1><a href="#x" id="link">link</a></body></html>',
		content_type='text/html',
	)
	yield server
	server.stop()


@pytest.fixture(scope='module')
def base_url(http_server: HTTPServer) -> str:
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None))
	await session.start()
	try:
		yield session
	finally:
		await session.kill()


async def _navigate(session: BrowserSession, url: str) -> None:
	from browser_use.browser.events import NavigateToUrlEvent

	await session.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=False))


async def test_dom_build_timeout_returns_minimal_state(
	monkeypatch: pytest.MonkeyPatch, browser_session: BrowserSession, base_url: str
):
	"""When the DOM build hangs, the handler must abort within the cap and
	return an empty selector_map instead of holding the event slot for the
	full 30s budget. The screenshot path is untouched, so it should resolve
	normally and survive in the returned state."""
	monkeypatch.setattr(dom_watchdog_module, 'DOM_BUILD_TIMEOUT_S', 0.3)
	monkeypatch.setattr(dom_watchdog_module, 'SCREENSHOT_TIMEOUT_S', 10.0)

	await _navigate(browser_session, f'{base_url}/page')

	watchdog = browser_session._dom_watchdog
	assert watchdog is not None, 'DOM watchdog should be attached after session.start()'

	release = asyncio.Event()  # never set — simulates indefinite hang

	async def _hanging_dom_build(previous_state=None):
		await release.wait()
		return SerializedDOMState(_root=None, selector_map={})

	monkeypatch.setattr(watchdog, '_build_dom_tree_without_highlights', _hanging_dom_build)

	start = time.monotonic()
	state = await browser_session.get_browser_state_summary(include_screenshot=True)
	elapsed = time.monotonic() - start

	# DOM build aborted at the cap → empty selector_map fallback
	assert state.dom_state is not None
	assert state.dom_state.selector_map == {}
	# Screenshot path was independent and unblocked — must survive
	assert state.screenshot is not None and len(state.screenshot) > 0
	# Bounded by the cap plus margin; nowhere near 30s
	assert elapsed < 10.0, f'handler took {elapsed:.2f}s; expected < 10s'

	release.set()  # let the orphaned task unwind cleanly


async def test_screenshot_timeout_returns_state_without_screenshot(
	monkeypatch: pytest.MonkeyPatch, browser_session: BrowserSession, base_url: str
):
	"""Symmetric to the DOM-build case: a hung screenshot must leave the
	rest of the state intact and just drop the screenshot field."""
	monkeypatch.setattr(dom_watchdog_module, 'DOM_BUILD_TIMEOUT_S', 10.0)
	monkeypatch.setattr(dom_watchdog_module, 'SCREENSHOT_TIMEOUT_S', 0.3)

	await _navigate(browser_session, f'{base_url}/page')

	watchdog = browser_session._dom_watchdog
	assert watchdog is not None

	release = asyncio.Event()

	async def _hanging_screenshot():
		await release.wait()
		return 'never_returned'

	monkeypatch.setattr(watchdog, '_capture_clean_screenshot', _hanging_screenshot)

	start = time.monotonic()
	state = await browser_session.get_browser_state_summary(include_screenshot=True)
	elapsed = time.monotonic() - start

	assert state.screenshot is None
	# DOM path was independent — must produce a real, non-empty selector_map
	assert state.dom_state is not None
	assert state.dom_state.selector_map  # the test page has interactive elements
	assert elapsed < 10.0, f'handler took {elapsed:.2f}s; expected < 10s'

	release.set()


async def test_healthy_path_preserves_results(browser_session: BrowserSession, base_url: str):
	"""Sanity check: with default caps the wrap is transparent on the happy
	path. If this regresses, every state build pays the timeout cost."""
	await _navigate(browser_session, f'{base_url}/page')

	state = await browser_session.get_browser_state_summary(include_screenshot=True)

	assert state.dom_state is not None
	assert state.dom_state.selector_map, 'expected interactive elements in /page'
	assert state.screenshot is not None and len(state.screenshot) > 0
	assert state.url.endswith('/page')
