"""Regression tests for AboutBlankWatchdog last-tab protection.

AboutBlankWatchdog.on_TabClosedEvent must create a replacement about:blank tab
when the LAST page tab is closed, otherwise Chrome exits and the whole browser
session dies.

TabClosedEvent is dispatched from two places with different timing:
- BrowserSession.on_CloseTabEvent dispatches it BEFORE Target.closeTarget runs,
  so the closing tab is still present in the target list.
- SessionManager._handle_target_detached dispatches it AFTER the target was
  fully removed, so the closing tab is already gone.

The remaining-tab count must therefore exclude the tab named by the event,
otherwise either the last-tab protection never fires (pre-close dispatch,
regressed in #3766) or a blank tab is created even though other tabs remain
(#3755).
"""

from typing import Any
from unittest.mock import MagicMock

from bubus import EventBus
from websockets.protocol import State

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import BaseEvent, TabClosedEvent, TabCreatedEvent
from browser_use.browser.watchdogs.aboutblank_watchdog import AboutBlankWatchdog


def _target_info(target_id: str, url: str = 'https://example.com') -> dict[str, Any]:
	return {
		'targetId': target_id,
		'type': 'page',
		'title': 'page',
		'url': url,
		'attached': True,
		'canAccessOpener': False,
	}


def _make_watchdog(
	monkeypatch, page_targets: list[dict[str, Any]], created_targets: list[str]
) -> tuple[AboutBlankWatchdog, MagicMock]:
	"""Build an AboutBlankWatchdog over an unstarted BrowserSession with fake CDP helpers."""
	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None))

	# Make is_cdp_connected return True without a real WebSocket
	fake_cdp_client = MagicMock()
	fake_cdp_client.ws.state = State.OPEN
	browser_session._cdp_client_root = fake_cdp_client

	async def fake_get_all_pages(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
		return page_targets

	async def fake_create_new_page(url: str = 'about:blank', **kwargs: Any) -> str:
		created_targets.append(url)
		return f'new-target-{len(created_targets)}'

	monkeypatch.setattr(browser_session, '_cdp_get_all_pages', fake_get_all_pages)
	monkeypatch.setattr(browser_session, '_cdp_create_new_page', fake_create_new_page)

	# Stub dispatch so tests never drive a real (unstarted) bubus event loop
	event_bus = EventBus()
	dispatch_mock = MagicMock(return_value=None)
	monkeypatch.setattr(event_bus, 'dispatch', dispatch_mock)

	watchdog = AboutBlankWatchdog(browser_session=browser_session, event_bus=event_bus)

	async def fake_screensaver() -> None:
		return None

	monkeypatch.setattr(watchdog, '_show_dvd_screensaver_on_about_blank_tabs', fake_screensaver)
	return watchdog, dispatch_mock


def _dispatched_tab_created_events(dispatch_mock: MagicMock) -> list[TabCreatedEvent]:
	return [
		call.args[0]
		for call in dispatch_mock.call_args_list
		if call.args and isinstance(call.args[0], BaseEvent) and isinstance(call.args[0], TabCreatedEvent)
	]


async def test_closing_last_tab_creates_replacement_tab(monkeypatch):
	"""Pre-close dispatch with only the closing tab listed: a replacement about:blank
	tab must be created BEFORE the close lands, or Chrome exits entirely."""
	created: list[str] = []
	watchdog, dispatch_mock = _make_watchdog(monkeypatch, [_target_info('closing-tab')], created)

	await watchdog.on_TabClosedEvent(TabClosedEvent(target_id='closing-tab'))

	assert created, 'AboutBlankWatchdog must create a replacement about:blank tab when the last tab is closed'
	tab_created_events = _dispatched_tab_created_events(dispatch_mock)
	assert tab_created_events, 'TabCreatedEvent must be dispatched so watchdogs initialize the replacement tab'
	assert tab_created_events[0].target_id == f'new-target-{len(created)}'
	assert tab_created_events[0].url == 'about:blank'


async def test_closing_one_of_two_tabs_does_not_create_blank_tab(monkeypatch):
	"""Pre-close dispatch with another tab remaining: no extra blank tab (#3755)."""
	created: list[str] = []
	watchdog, dispatch_mock = _make_watchdog(
		monkeypatch,
		[_target_info('closing-tab'), _target_info('other-tab')],
		created,
	)

	await watchdog.on_TabClosedEvent(TabClosedEvent(target_id='closing-tab'))

	assert created == []
	assert _dispatched_tab_created_events(dispatch_mock) == []


async def test_post_detach_close_with_remaining_tab_does_not_create_blank_tab(monkeypatch):
	"""Post-detach dispatch: the closed tab is already removed, one tab remains."""
	created: list[str] = []
	watchdog, dispatch_mock = _make_watchdog(monkeypatch, [_target_info('other-tab')], created)

	await watchdog.on_TabClosedEvent(TabClosedEvent(target_id='closed-tab'))

	assert created == []
	assert _dispatched_tab_created_events(dispatch_mock) == []


async def test_post_detach_close_of_last_tab_creates_replacement_tab(monkeypatch):
	"""Post-detach dispatch with no tabs left: replacement tab must be created."""
	created: list[str] = []
	watchdog, dispatch_mock = _make_watchdog(monkeypatch, [], created)

	await watchdog.on_TabClosedEvent(TabClosedEvent(target_id='closed-tab'))

	assert created, 'AboutBlankWatchdog must create a replacement about:blank tab when no tabs remain'
	tab_created_events = _dispatched_tab_created_events(dispatch_mock)
	assert tab_created_events, 'TabCreatedEvent must be dispatched so watchdogs initialize the replacement tab'
	assert tab_created_events[0].url == 'about:blank'
