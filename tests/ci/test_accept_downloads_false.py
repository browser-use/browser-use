"""accept_downloads=False must deny CDP downloads and skip auto-fetch."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog


def _make_watchdog(tmp_path: Path, *, accept_downloads: bool) -> tuple[DownloadsWatchdog, AsyncMock]:
	profile = MagicMock()
	profile.downloads_path = tmp_path
	profile.accept_downloads = accept_downloads
	profile.auto_download_pdfs = True

	set_download_behavior = AsyncMock()
	cdp_client = MagicMock()
	cdp_client.send = MagicMock()
	cdp_client.send.Browser = MagicMock()
	cdp_client.send.Browser.setDownloadBehavior = set_download_behavior
	cdp_client.register = MagicMock()
	cdp_client.register.Browser = MagicMock()
	cdp_client.register.Browser.downloadWillBegin = MagicMock()
	cdp_client.register.Browser.downloadProgress = MagicMock()
	cdp_client.register.Network = MagicMock()
	cdp_client.register.Network.responseReceived = MagicMock()
	cdp_client.send.Network = MagicMock()
	cdp_client.send.Network.enable = AsyncMock()

	session_manager = MagicMock()
	browser_session = MagicMock()
	browser_session.browser_profile = profile
	browser_session.cdp_client = cdp_client
	browser_session.session_manager = session_manager
	browser_session.is_local = True
	browser_session.get_or_create_cdp_session = AsyncMock(return_value=MagicMock(session_id='sess'))

	event_bus = MagicMock()
	wd = DownloadsWatchdog.model_construct(browser_session=browser_session, event_bus=event_bus)
	return wd, set_download_behavior


@pytest.mark.asyncio
async def test_set_download_behavior_denies_when_accept_downloads_false(tmp_path: Path):
	wd, set_download_behavior = _make_watchdog(tmp_path, accept_downloads=False)
	await wd.attach_to_target('target-1')
	set_download_behavior.assert_awaited()
	await_args = set_download_behavior.await_args
	assert await_args is not None
	params = await_args.kwargs['params']
	assert params['behavior'] == 'deny'


@pytest.mark.asyncio
async def test_set_download_behavior_allows_when_accept_downloads_true(tmp_path: Path):
	wd, set_download_behavior = _make_watchdog(tmp_path, accept_downloads=True)
	await wd.attach_to_target('target-1')
	await_args = set_download_behavior.await_args
	assert await_args is not None
	params = await_args.kwargs['params']
	assert params['behavior'] == 'allow'


@pytest.mark.asyncio
async def test_download_file_from_url_skipped_when_accept_downloads_false(tmp_path: Path):
	wd, _ = _make_watchdog(tmp_path, accept_downloads=False)
	get_session = wd.browser_session.get_or_create_cdp_session
	assert isinstance(get_session, AsyncMock)
	result = await wd.download_file_from_url('https://example.com/a.pdf', 'target-1')
	assert result is None
	# None is also the fetch-failure result. The skip must return before any CDP session.
	get_session.assert_not_awaited()


def test_auto_download_requires_accept_downloads(tmp_path: Path):
	wd, _ = _make_watchdog(tmp_path, accept_downloads=False)
	assert wd._is_auto_download_enabled() is False
	wd.browser_session.browser_profile.accept_downloads = True
	assert wd._is_auto_download_enabled() is True
