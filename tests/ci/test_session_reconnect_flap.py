"""Tests for CDP reconnect flap detection.

Covers issue #4471 (Part 2): when reconnects succeed at the WS layer but the
new socket dies immediately, _auto_reconnect's per-cycle attempt cap doesn't
trigger and the loop runs forever. ReconnectFlapDetector caps cross-cycle
reconnect successes in a sliding window; BrowserSession surfaces a terminal
BrowserErrorEvent the first time the threshold is crossed and refuses to spawn
new reconnect tasks while the latch is set.
"""

from __future__ import annotations

import time

import pytest

from browser_use.browser.events import BrowserErrorEvent
from browser_use.browser.session import BrowserSession, ReconnectFlapDetector

# ---------------------------------------------------------------------------
# Detector — pure unit tests, no browser
# ---------------------------------------------------------------------------


def test_detector_starts_clean():
	d = ReconnectFlapDetector(window_seconds=60.0, max_events=5)
	assert d.recent_count == 0
	assert d.should_give_up() is False


def test_detector_under_threshold_does_not_trigger():
	d = ReconnectFlapDetector(window_seconds=60.0, max_events=5)
	for _ in range(4):
		d.record_success()
	assert d.recent_count == 4
	assert d.should_give_up() is False


def test_detector_at_threshold_latches():
	d = ReconnectFlapDetector(window_seconds=60.0, max_events=5)
	for _ in range(5):
		d.record_success()
	assert d.should_give_up() is True
	# Once latched, stays latched.
	assert d.should_give_up() is True


def test_detector_evicts_outside_window(monkeypatch: pytest.MonkeyPatch):
	"""Events older than window_seconds drop out of the sliding window."""
	now = [1000.0]
	monkeypatch.setattr(time, 'monotonic', lambda: now[0])

	# Spread across the window — never crosses threshold.
	d = ReconnectFlapDetector(window_seconds=10.0, max_events=3)
	d.record_success()  # t=1000
	now[0] = 1011.0  # first event now outside the window
	d.record_success()
	now[0] = 1022.0  # second event now outside
	d.record_success()
	assert d.recent_count == 1
	assert d.should_give_up() is False

	# Bunched inside the window — crosses threshold.
	d2 = ReconnectFlapDetector(window_seconds=10.0, max_events=3)
	now[0] = 2000.0
	for _ in range(3):
		d2.record_success()
	assert d2.should_give_up() is True


def test_detector_reset_clears_latch_and_history():
	d = ReconnectFlapDetector(window_seconds=60.0, max_events=2)
	d.record_success()
	d.record_success()
	assert d.should_give_up() is True
	d.reset()
	assert d.recent_count == 0
	assert d.should_give_up() is False


def test_detector_rejects_invalid_config():
	with pytest.raises(AssertionError):
		ReconnectFlapDetector(window_seconds=0, max_events=5)
	with pytest.raises(AssertionError):
		ReconnectFlapDetector(window_seconds=10, max_events=0)


# ---------------------------------------------------------------------------
# BrowserSession wiring — drives the real _handle_ws_drop code path
# ---------------------------------------------------------------------------


@pytest.fixture
async def session():
	"""A BrowserSession with tight flap thresholds and no real browser.

	We never call start() — these tests drive the in-process WS-drop handler
	to verify the dispatch latch and reset behaviour. The detector thresholds
	are overridden so the test doesn't depend on the production constants.

	The event_bus is stopped on teardown because bubus auto-starts a background
	_run_loop task on first dispatch; leaving it running stalls the
	session-scoped pytest-asyncio loop at end-of-session.
	"""
	s = BrowserSession()
	s._reconnect_flap_detector = ReconnectFlapDetector(window_seconds=60.0, max_events=3)
	# cdp_url is a read-only property on BrowserSession that proxies to
	# browser_profile — pretend we're attached so _handle_ws_drop doesn't bail.
	s.browser_profile.cdp_url = 'http://localhost:9222/'
	try:
		yield s
	finally:
		await s.event_bus.stop(clear=True, timeout=5)


async def test_handle_ws_drop_dispatches_flap_event_exactly_once(session: BrowserSession):
	"""Latching: many WS drops while the flap is tripped → one BrowserErrorEvent."""
	events: list[BrowserErrorEvent] = []

	async def _collect(e: BrowserErrorEvent) -> None:
		events.append(e)

	session.event_bus.on(BrowserErrorEvent, _collect)

	# Drive 3 successful reconnects → detector latches at threshold=3.
	flap = session._reconnect_flap()
	for _ in range(3):
		flap.record_success()

	# Three subsequent WS drops while latched should produce exactly ONE event.
	session._handle_ws_drop(None)
	session._handle_ws_drop(None)
	session._handle_ws_drop(None)

	await session.event_bus.wait_until_idle(timeout=2.0)

	assert len(events) == 1, f'expected exactly one ReconnectionFlapping event, got {len(events)}'
	(err,) = events
	assert err.error_type == 'ReconnectionFlapping'
	assert err.details['window_seconds'] == 60.0
	assert err.details['max_events'] == 3
	assert err.details['recent_count'] == 3


async def test_handle_ws_drop_under_threshold_does_not_dispatch(session: BrowserSession):
	"""Under threshold, no flap event fires and the dispatch latch stays clear."""
	events: list[BrowserErrorEvent] = []

	async def _collect(e: BrowserErrorEvent) -> None:
		events.append(e)

	session.event_bus.on(BrowserErrorEvent, _collect)

	flap = session._reconnect_flap()
	flap.record_success()  # 1 of 3 — well under
	flap.record_success()  # 2 of 3 — still under

	# Drive the drop handler. We don't assert on whether a reconnect task is
	# created (that requires a real CDP client) — we only assert the flap
	# pathway stays silent.
	session._handle_ws_drop(None)
	await session.event_bus.wait_until_idle(timeout=1.0)

	assert events == []
	assert session._reconnect_flap_dispatched is False


async def test_reset_clears_flap_state(session: BrowserSession):
	"""reset() restores a fresh reconnect budget after a give-up."""
	flap = session._reconnect_flap()
	for _ in range(3):
		flap.record_success()
	session._handle_ws_drop(None)  # triggers dispatch + sets the latch
	assert session._reconnect_flap_dispatched is True

	await session.reset()

	assert session._reconnect_flap_detector is not None
	assert session._reconnect_flap_detector.recent_count == 0
	assert session._reconnect_flap_detector.should_give_up() is False
	assert session._reconnect_flap_dispatched is False
