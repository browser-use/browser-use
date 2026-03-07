from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from bubus import EventBus
from cdp_use.cdp.target import TargetID

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog


def _build_session(session_manager: Any) -> BrowserSession:
	return BrowserSession.model_construct(
		id='downloads-watchdog-test',
		browser_profile=BrowserProfile(headless=True, user_data_dir=None),
		event_bus=EventBus(),
		agent_focus_target_id=None,
		session_manager=session_manager,
	)


@pytest.mark.asyncio
async def test_check_for_pdf_viewer_skips_missing_target_without_warning(monkeypatch):
	session_manager = Mock()
	session_manager.get_target.return_value = None
	session = _build_session(session_manager)
	get_session = AsyncMock()
	object.__setattr__(session, 'get_or_create_cdp_session', get_session)
	warning = Mock()
	monkeypatch.setattr(session.logger, 'warning', warning)
	watchdog = DownloadsWatchdog(event_bus=EventBus(), browser_session=session)

	result = await watchdog.check_for_pdf_viewer(TargetID('target-missing'))

	assert result is False
	get_session.assert_not_awaited()
	warning.assert_not_called()


@pytest.mark.asyncio
async def test_check_for_pdf_viewer_suppresses_expected_detach_warning(monkeypatch):
	session_manager = Mock()
	session_manager.get_target.return_value = SimpleNamespace(url='https://example.com/document')
	session = _build_session(session_manager)
	get_session = AsyncMock(side_effect=ValueError('Target target-123 not found - may have detached or never existed'))
	object.__setattr__(session, 'get_or_create_cdp_session', get_session)
	warning = Mock()
	monkeypatch.setattr(session.logger, 'warning', warning)
	watchdog = DownloadsWatchdog(event_bus=EventBus(), browser_session=session)

	result = await watchdog.check_for_pdf_viewer(TargetID('target-123'))

	assert result is False
	get_session.assert_awaited_once()
	warning.assert_not_called()


@pytest.mark.asyncio
async def test_check_for_pdf_viewer_keeps_unexpected_session_warning(monkeypatch):
	session_manager = Mock()
	session_manager.get_target.return_value = SimpleNamespace(url='https://example.com/document')
	session = _build_session(session_manager)
	get_session = AsyncMock(side_effect=ValueError('unexpected session lookup failure'))
	object.__setattr__(session, 'get_or_create_cdp_session', get_session)
	warning = Mock()
	monkeypatch.setattr(session.logger, 'warning', warning)
	watchdog = DownloadsWatchdog(event_bus=EventBus(), browser_session=session)

	result = await watchdog.check_for_pdf_viewer(TargetID('target-456'))

	assert result is False
	warning.assert_called_once_with('[DownloadsWatchdog] No session found for target-456: unexpected session lookup failure')


@pytest.mark.asyncio
async def test_check_for_pdf_viewer_skips_when_session_manager_missing(monkeypatch):
	session = _build_session(None)
	get_session = AsyncMock()
	object.__setattr__(session, 'get_or_create_cdp_session', get_session)
	debug = Mock()
	monkeypatch.setattr(session.logger, 'debug', debug)
	watchdog = DownloadsWatchdog(event_bus=EventBus(), browser_session=session)

	result = await watchdog.check_for_pdf_viewer(TargetID('target-shutdown'))

	assert result is False
	get_session.assert_not_awaited()
	assert any('session manager is unavailable during shutdown' in str(call.args[0]) for call in debug.call_args_list)


@pytest.mark.asyncio
async def test_check_for_pdf_viewer_skips_when_session_manager_disappears_after_session_lookup(monkeypatch):
	session_manager = Mock()
	session_manager.get_target.return_value = SimpleNamespace(url='https://example.com/document')
	session = _build_session(session_manager)

	async def get_session(target_id, focus=False):
		object.__setattr__(session, 'session_manager', None)
		return SimpleNamespace(target_id=target_id)

	object.__setattr__(session, 'get_or_create_cdp_session', AsyncMock(side_effect=get_session))
	debug = Mock()
	monkeypatch.setattr(session.logger, 'debug', debug)
	watchdog = DownloadsWatchdog(event_bus=EventBus(), browser_session=session)

	result = await watchdog.check_for_pdf_viewer(TargetID('target-race'))

	assert result is False
	assert any('session manager disappeared after session lookup' in str(call.args[0]) for call in debug.call_args_list)
