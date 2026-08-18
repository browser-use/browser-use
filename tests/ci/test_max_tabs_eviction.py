"""Tests for BrowserProfile.max_tabs (#5484).

Long-running sessions accumulate tabs because nothing ever closes them. `max_tabs`
caps the open tab count by evicting the oldest evictable tab whenever a new tab
pushes the session over the limit.

Covers:
1. Default (None) keeps the previous unbounded behaviour.
2. A configured cap converges to that many tabs, keeping the *newest* ones.
3. The tab the agent is focused on is never the one evicted.
4. The tab that was just opened is never evicted out from under its own navigation.
5. The field rejects a cap below 1 (which could otherwise close every tab).
"""

import asyncio

import pytest
from pydantic import ValidationError
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import SwitchTabEvent
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
	"""A tab already queued for eviction must not be closed if focus lands on it first.

	`CloseTabEvent` for an evicted tab is dispatched as a background task rather than
	awaited inline, so several event-loop turns can pass before it actually runs. If the
	agent switches onto that exact tab in the meantime, closing it anyway would violate
	the "never evict the focused tab" guarantee. `_evict_tab` re-checks focus immediately
	before closing to close that window — exercised directly here since winning the real
	race deterministically isn't possible from a test.
	"""
	session = await _make_session(max_tabs=2)
	try:
		opened = await _open_tabs(tools, session, base_url, 2)
		target_id = opened[0]
		assert target_id in _open_tab_ids(session)

		# Simulate _enforce_max_tabs having just selected target_id for eviction, then focus
		# moving onto it before the queued close executes.
		session._pending_tab_evictions.add(target_id)
		await session.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
		assert session.agent_focus_target_id == target_id

		await session._evict_tab(target_id)

		assert target_id in _open_tab_ids(session)
		assert target_id not in session._pending_tab_evictions
	finally:
		await session.kill()


def test_max_tabs_rejects_values_below_one():
	"""max_tabs=0 would evict every tab, so pydantic must reject it up front."""
	with pytest.raises(ValidationError):
		BrowserProfile(max_tabs=0)

	assert BrowserProfile(max_tabs=1).max_tabs == 1
	assert BrowserProfile().max_tabs is None
