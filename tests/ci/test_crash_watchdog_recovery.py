"""Renderer-crash detection and recovery (CrashWatchdog).

A renderer crash (OOM, WebGL context loss, sad-tab) is not a target detach: Chrome emits
`Target.targetCrashed` but keeps the target attached and in the target list. `SessionManager`'s
auto-recovery is driven by `Target.detachedFromTarget`, so it never ran for a crash, and the
agent kept issuing actions against a dead renderer until its step budget was gone.

These tests drive a real headless Chrome and crash a real renderer via `Page.crash`.
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import BrowserErrorEvent

# Page.crash kills the renderer mid-command, so the command's own response never arrives.
CRASH_COMMAND_TIMEOUT = 5.0
# Crash detection + reload + liveness check, with headroom for a loaded CI machine.
RECOVERY_TIMEOUT = 30.0


@pytest.fixture(scope='function')
async def crash_session():
	"""A dedicated browser session per test: these tests deliberately kill renderers."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			enable_default_extensions=False,
		)
	)
	await session.start()
	yield session
	await session.kill()
	await session.event_bus.stop(clear=True, timeout=5)


@pytest.fixture(scope='function')
def heavy_page(httpserver: HTTPServer) -> str:
	httpserver.expect_request('/heavy').respond_with_data(
		'<html><body><h1 id="marker">still alive</h1></body></html>',
		content_type='text/html',
	)
	return httpserver.url_for('/heavy')


async def _crash_renderer(session: BrowserSession, target_id: str | None = None) -> None:
	"""Kill a real renderer process.

	Page.crash kills the renderer mid-command, so it either errors with 'Target crashed' or
	never answers at all. Both mean the crash landed; neither is what we are asserting on.
	"""
	cdp_session = await session.get_or_create_cdp_session(target_id, focus=target_id is None)
	try:
		await asyncio.wait_for(
			cdp_session.cdp_client.send.Page.crash(session_id=cdp_session.session_id),
			timeout=CRASH_COMMAND_TIMEOUT,
		)
	except (TimeoutError, RuntimeError):
		pass


async def _wait_for_crash_event(events: list[BrowserErrorEvent], timeout: float = RECOVERY_TIMEOUT) -> BrowserErrorEvent:
	loop = asyncio.get_event_loop()
	deadline = loop.time() + timeout
	while loop.time() < deadline:
		crashes = [e for e in events if e.error_type == 'TargetCrash']
		if crashes:
			return crashes[0]
		await asyncio.sleep(0.1)
	raise AssertionError('No TargetCrash BrowserErrorEvent was emitted - the crash went undetected')


def _collect_browser_errors(session: BrowserSession) -> list[BrowserErrorEvent]:
	events: list[BrowserErrorEvent] = []
	session.event_bus.on(BrowserErrorEvent, lambda event: events.append(event))
	return events


async def test_renderer_crash_is_detected_and_surfaced(crash_session: BrowserSession, heavy_page: str):
	"""The crash must be reported as a TargetCrash, not swallowed into element-not-found noise."""
	await crash_session.navigate_to(heavy_page, new_tab=False)
	events = _collect_browser_errors(crash_session)
	crashed_target_id = crash_session.agent_focus_target_id

	await _crash_renderer(crash_session)

	crash_event = await _wait_for_crash_event(events)
	assert crash_event.details['target_id'] == crashed_target_id
	assert crash_event.details['was_agent_focus'] is True


async def test_agent_can_keep_working_after_a_renderer_crash(crash_session: BrowserSession, heavy_page: str):
	"""The whole point: after a crash the session must still be usable, not wedged."""
	await crash_session.navigate_to(heavy_page, new_tab=False)
	events = _collect_browser_errors(crash_session)

	await _crash_renderer(crash_session)
	crash_event = await _wait_for_crash_event(events)
	assert crash_event.details['recovered'] is True, 'crashed tab was never brought back to life'

	# A CDP round-trip on the recovered focus target must succeed within a bounded time.
	cdp_session = await crash_session.get_or_create_cdp_session()
	result = await asyncio.wait_for(
		cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': '1 + 1', 'returnByValue': True},
			session_id=cdp_session.session_id,
		),
		timeout=RECOVERY_TIMEOUT,
	)
	assert result['result']['value'] == 2

	# And the agent can still navigate afterwards.
	await asyncio.wait_for(crash_session.navigate_to(heavy_page, new_tab=False), timeout=RECOVERY_TIMEOUT)


async def test_crash_in_background_tab_is_attributed_to_that_tab(crash_session: BrowserSession, heavy_page: str):
	"""Regression: the handler ignored the event payload and blamed a closure-captured target.

	Because every CDPSession shares one CDP client, the old per-target registration installed a
	duplicate global handler per tab, so a single crash was misattributed and healthy tabs were
	reloaded. The crash must now be pinned to the target Chrome actually names.
	"""
	await crash_session.navigate_to(heavy_page, new_tab=False)
	focus_target_id = crash_session.agent_focus_target_id

	background_target_id = await crash_session._cdp_create_new_page(heavy_page)
	await asyncio.sleep(1.0)  # let the new target attach
	assert background_target_id != focus_target_id

	events = _collect_browser_errors(crash_session)
	await _crash_renderer(crash_session, target_id=background_target_id)

	crash_event = await _wait_for_crash_event(events)
	assert crash_event.details['target_id'] == background_target_id
	assert crash_event.details['was_agent_focus'] is False

	# Exactly one crash was reported - not one per open tab.
	crashes = [e for e in events if e.error_type == 'TargetCrash']
	assert len(crashes) == 1, f'expected 1 crash event, got {len(crashes)} (duplicate global handlers)'

	# The agent's own tab was untouched by someone else's crash.
	assert crash_session.agent_focus_target_id == focus_target_id
