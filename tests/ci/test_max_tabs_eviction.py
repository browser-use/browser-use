"""Tests for BrowserProfile.max_tabs (#5484).

Long-running sessions accumulate tabs because nothing ever closes them. `max_tabs`
caps the open tab count by evicting the oldest evictable tab whenever a new tab
pushes the session over the limit.

Covers:
1. Default (None) keeps the previous unbounded behaviour.
2. A configured cap converges to that many tabs, keeping the *newest* ones.
3. The tab the agent is focused on is never the one evicted.
4. The tab that was just opened is never evicted out from under its own navigation.
5. A tab that becomes focused after eviction was scheduled for it is spared, and the cap
   still ends up enforced against a different tab instead.
6. A scheduled eviction that never completes (dropped CloseTabEvent) is aged out instead
   of leaving its target permanently unevictable.
7. The field rejects a cap below 1 (which could otherwise close every tab).
"""

import asyncio
import time

import pytest
from pydantic import ValidationError
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import CloseTabEvent
from browser_use.tools.service import Tools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def http_server():
	"""Session-scoped HTTP server serving a handful of distinct pages."""
	server = HTTPServer()
	server.start()

	for i in range(8):
		server.expect_request(f'/page{i}').respond_with_data(
			f'<!DOCTYPE html><html><head><title>Page {i}</title></head><body><h1>Page {i}</h1></body></html>',
			content_type='text/html',
		)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='function')
def tools():
	return Tools()


async def _make_session(max_tabs: int | None) -> BrowserSession:
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			max_tabs=max_tabs,
		)
	)
	await session.start()
	return session


def _open_tab_ids(session: BrowserSession) -> list[str]:
	return [target.target_id for target in session.session_manager.get_all_page_targets()]


async def _open_tabs(tools, session: BrowserSession, base_url: str, count: int) -> list[str]:
	"""Open `count` tabs and return their target ids in the order they were opened."""
	opened = []
	for i in range(count):
		await tools.navigate(url=f'{base_url}/page{i}', new_tab=True, browser_session=session)
		opened.append(session.agent_focus_target_id)
	return opened


async def _settle(session: BrowserSession, timeout: float = 20.0) -> list[str]:
	"""Wait until the tab set stops changing.

	Eviction is dispatched rather than awaited, so the session manager only reflects a
	closed tab once CDP detaches it. Waiting for quiescence (instead of a fixed sleep or
	a first-match-wins poll) keeps this stable on slow CI.
	"""
	loop = asyncio.get_event_loop()
	deadline = loop.time() + timeout
	previous: list[str] | None = None
	unchanged = 0

	while loop.time() < deadline:
		await asyncio.sleep(0.25)
		current = _open_tab_ids(session)
		unchanged = unchanged + 1 if current == previous else 0
		previous = current
		if unchanged >= 3:  # ~0.75s with no change
			break

	return _open_tab_ids(session)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_max_tabs_none_leaves_tabs_unbounded(tools, base_url):
	"""Default profile must not close anything — pure back-compat."""
	session = await _make_session(max_tabs=None)
	try:
		assert session.browser_profile.max_tabs is None

		opened = await _open_tabs(tools, session, base_url, 4)
		surviving = await _settle(session)

		# Every tab opened survives (plus whatever blank tab the session started with).
		assert set(opened).issubset(set(surviving))
		assert len(surviving) >= 4
	finally:
		await session.kill()


async def test_max_tabs_evicts_the_oldest_tabs_first(tools, base_url):
	"""Opening more tabs than the cap converges to exactly max_tabs, keeping the newest."""
	session = await _make_session(max_tabs=3)
	try:
		opened = await _open_tabs(tools, session, base_url, 6)
		surviving = await _settle(session)

		assert len(surviving) == 3
		# The three most recently opened tabs are the survivors — a regression that evicted
		# newest-first would keep the same count but fail here.
		assert set(surviving) == set(opened[-3:])
		assert not set(opened[:-3]) & set(surviving)
	finally:
		await session.kill()


async def test_max_tabs_never_evicts_the_focused_tab(tools, base_url):
	"""The agent's own tab must survive eviction, so it is never left without a page."""
	session = await _make_session(max_tabs=2)
	try:
		await _open_tabs(tools, session, base_url, 5)
		surviving = await _settle(session)

		assert len(surviving) == 2
		focus = session.agent_focus_target_id
		assert focus is not None
		assert focus in surviving
	finally:
		await session.kill()


async def test_max_tabs_one_keeps_the_tab_being_navigated_into(tools, base_url):
	"""A cap of 1 must not close the freshly created tab before its navigation lands.

	on_TabCreatedEvent runs before focus switches to the new tab, so without protecting
	the just-created target the cap would evict the very tab the agent just opened.
	"""
	session = await _make_session(max_tabs=1)
	try:
		opened = await _open_tabs(tools, session, base_url, 3)
		surviving = await _settle(session)

		assert surviving == [opened[-1]]
		assert session.agent_focus_target_id == opened[-1]

		# The surviving tab is still usable — it was navigated, not closed mid-flight.
		state = await session.get_browser_state_summary()
		assert state.url.endswith('/page2')
	finally:
		await session.kill()


async def test_max_tabs_spares_a_tab_focused_after_eviction_was_scheduled(tools, base_url):
	"""A tab already queued for eviction must not be closed if focus lands on it first,
	and the cap must still end up enforced against a different tab instead.

	`_enforce_max_tabs` dispatches `CloseTabEvent` without awaiting, so several event-loop
	turns can pass before `on_CloseTabEvent` actually runs it. If the agent switches onto
	that exact tab in the meantime, closing it anyway would violate the "never evict the
	focused tab" guarantee - and leaving the session over max_tabs would be its own bug.
	`on_CloseTabEvent` re-checks focus for pending-eviction targets immediately before doing
	the real close and re-runs enforcement if it skips one.

	Winning the real scheduling race deterministically isn't possible from a test, so this
	drives the exact same production entry point _enforce_max_tabs uses - dispatching
	`CloseTabEvent`, handled by the shared `on_CloseTabEvent` - with the race already having
	landed against us (target focused, eviction already marked pending).
	"""
	# max_tabs=None while opening tabs so real auto-eviction doesn't run concurrently and
	# make the outcome depend on unrelated timing; the cap below is applied by hand instead.
	session = await _make_session(max_tabs=None)
	try:
		opened = await _open_tabs(tools, session, base_url, 3)
		target_id, next_oldest_id = opened[0], opened[1]
		session.browser_profile.max_tabs = 2

		# Simulate _enforce_max_tabs having just selected target_id for eviction, then focus
		# moving onto it before the queued close executes.
		session._pending_tab_evictions[target_id] = time.monotonic()
		session.agent_focus_target_id = target_id

		await session.event_bus.dispatch(CloseTabEvent(target_id=target_id))

		assert target_id in _open_tab_ids(session)
		assert target_id not in session._pending_tab_evictions

		# The spared tab pushed the session back over the cap, so the skip path's re-run of
		# _enforce_max_tabs should have picked the next-oldest evictable tab instead.
		surviving = await _settle(session)
		assert len(surviving) == 2
		assert target_id in surviving
		assert next_oldest_id not in surviving
	finally:
		await session.kill()


async def test_max_tabs_recovers_a_pending_eviction_that_never_completed(tools, base_url):
	"""A target stuck in `_pending_tab_evictions` must not stay unevictable forever.

	If a scheduled close's `CloseTabEvent` is ever silently dropped (a CDP disconnect, the
	event bus torn down mid-flight), the target would otherwise be permanently excluded from
	`live` in `_enforce_max_tabs`, loosening the cap by one for the rest of the session. A
	stale (past `_MAX_TABS_EVICTION_STALE_AFTER`) pending entry must be dropped and the tab
	treated as evictable again on the next enforcement pass.
	"""
	from browser_use.browser.session import _MAX_TABS_EVICTION_STALE_AFTER

	session = await _make_session(max_tabs=None)
	try:
		opened = await _open_tabs(tools, session, base_url, 3)
		stuck_target_id = opened[0]

		# Simulate a scheduled eviction whose CloseTabEvent never actually ran.
		session._pending_tab_evictions[stuck_target_id] = time.monotonic() - _MAX_TABS_EVICTION_STALE_AFTER - 1
		session.browser_profile.max_tabs = 2

		session._enforce_max_tabs()
		surviving = await _settle(session)

		assert len(surviving) == 2
		assert stuck_target_id not in surviving
		assert stuck_target_id not in session._pending_tab_evictions
	finally:
		await session.kill()


def test_max_tabs_rejects_values_below_one():
	"""max_tabs=0 would evict every tab, so pydantic must reject it up front."""
	with pytest.raises(ValidationError):
		BrowserProfile(max_tabs=0)

	assert BrowserProfile(max_tabs=1).max_tabs == 1
	assert BrowserProfile().max_tabs is None
