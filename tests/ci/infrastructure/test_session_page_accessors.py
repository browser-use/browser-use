"""Page accessors must survive the reset/stop/kill teardown window."""

import pytest

from browser_use.browser import BrowserProfile, BrowserSession


@pytest.fixture
def torn_down_session() -> BrowserSession:
	"""A session caught mid-teardown: manager cleared, focus not yet."""
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	session.agent_focus_target_id = 'stale-target-id'
	session.session_manager = None
	return session


async def test_get_current_page_url_returns_blank_when_torn_down(torn_down_session):
	assert await torn_down_session.get_current_page_url() == 'about:blank'


async def test_get_current_page_title_falls_back_when_torn_down(torn_down_session):
	assert await torn_down_session.get_current_page_title() == 'Unknown page title'
