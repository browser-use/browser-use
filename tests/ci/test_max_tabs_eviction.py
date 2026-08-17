"""Tests for BrowserProfile.max_tabs (#5484).

Long-running sessions accumulate tabs because nothing ever closes them. `max_tabs`
caps the open tab count by evicting the oldest non-focused tab whenever a new tab
pushes the session over the limit.

Covers:
1. Default (None) keeps the previous unbounded behaviour.
2. A configured cap converges to that many tabs no matter how many are opened.
3. The tab the agent is focused on is never the one evicted.
4. The field rejects a cap below 1 (which could otherwise close every tab).
"""

import asyncio

import pytest
from pydantic import ValidationError
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
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


def _tab_count(session: BrowserSession) -> int:
	return len(session.session_manager.get_all_page_targets())


async def _settle(session: BrowserSession, timeout: float = 5.0) -> int:
	"""Wait for eviction (dispatched, not awaited) to drain, then report the tab count."""
	deadline = asyncio.get_event_loop().time() + timeout
	max_tabs = session.browser_profile.max_tabs
	while asyncio.get_event_loop().time() < deadline:
		await asyncio.sleep(0.25)
		if max_tabs is None or _tab_count(session) <= max_tabs:
			break
	return _tab_count(session)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_max_tabs_none_leaves_tabs_unbounded(tools, base_url):
	"""Default profile must not close anything — pure back-compat."""
	session = await _make_session(max_tabs=None)
	try:
		assert session.browser_profile.max_tabs is None

		for i in range(4):
			await tools.navigate(url=f'{base_url}/page{i}', new_tab=True, browser_session=session)
		await asyncio.sleep(1.0)

		# 4 opened tabs all survive (plus whatever blank tab the session started with).
		assert _tab_count(session) >= 4
	finally:
		await session.kill()


async def test_max_tabs_evicts_down_to_the_cap(tools, base_url):
	"""Opening more tabs than the cap converges to exactly max_tabs."""
	session = await _make_session(max_tabs=3)
	try:
		for i in range(6):
			await tools.navigate(url=f'{base_url}/page{i}', new_tab=True, browser_session=session)

		assert await _settle(session) == 3
	finally:
		await session.kill()


async def test_max_tabs_never_evicts_the_focused_tab(tools, base_url):
	"""The agent's own tab must survive eviction, so it is never left without a page."""
	session = await _make_session(max_tabs=2)
	try:
		for i in range(5):
			await tools.navigate(url=f'{base_url}/page{i}', new_tab=True, browser_session=session)

		assert await _settle(session) == 2

		focus = session.agent_focus_target_id
		assert focus is not None
		surviving = {target.target_id for target in session.session_manager.get_all_page_targets()}
		assert focus in surviving
	finally:
		await session.kill()


def test_max_tabs_rejects_values_below_one():
	"""max_tabs=0 would evict every tab, so pydantic must reject it up front."""
	with pytest.raises(ValidationError):
		BrowserProfile(max_tabs=0)

	assert BrowserProfile(max_tabs=1).max_tabs == 1
	assert BrowserProfile().max_tabs is None
