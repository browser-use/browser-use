"""Regression tests for Agent.close() keep-alive browser cleanup."""

from typing import Any, cast

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession


def _make_session(*, keep_alive: bool, is_local: bool, cdp_url: str | None = None) -> tuple[BrowserSession, Any]:
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=keep_alive,
			is_local=is_local,
			cdp_url=cdp_url,
		),
		cdp_url=cdp_url,
	)
	event_bus = cast(Any, session.event_bus)
	event_bus._on_idle = object()
	return session, event_bus


async def test_agent_close_preserves_remote_keep_alive_event_bus(mock_llm):
	session, event_bus = _make_session(keep_alive=True, is_local=False, cdp_url='ws://browser.example/devtools/browser/1')
	original_event_bus = session.event_bus
	original_queue = event_bus.event_queue
	original_on_idle = event_bus._on_idle
	agent = Agent(task='keep remote browser alive', llm=mock_llm, browser_session=session)

	await agent.close()

	assert session.event_bus is original_event_bus
	assert event_bus.event_queue is original_queue
	assert event_bus._on_idle is original_on_idle


async def test_agent_close_still_cleans_local_keep_alive_event_bus(mock_llm):
	session, event_bus = _make_session(keep_alive=True, is_local=True)
	agent = Agent(task='keep local browser alive', llm=mock_llm, browser_session=session)

	await agent.close()

	assert event_bus.event_queue is None
	assert event_bus._on_idle is None


async def test_agent_close_kills_non_keep_alive_browser_session(mock_llm):
	session, event_bus = _make_session(keep_alive=False, is_local=False, cdp_url='ws://browser.example/devtools/browser/1')
	original_event_bus = session.event_bus
	agent = Agent(task='close browser session', llm=mock_llm, browser_session=session)

	await agent.close()

	assert session.event_bus is not original_event_bus
