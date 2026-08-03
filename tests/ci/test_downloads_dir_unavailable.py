"""Regression test for downloads when the directory cannot be created.

On some platforms (virtualized/redirected folders such as OneDrive-backed
Downloads on Windows) ``Path.mkdir`` raises ``OSError`` even though the parent
reports as existing. PR #5358 originally only skipped the initial snapshot
capture in that case; CDP setup, ``download_file_from_url``, and
``trigger_pdf_download`` still used the unusable path and re-attempted
``os.makedirs`` on every download.

This test drives ``DownloadsWatchdog`` with a broken directory and asserts that
downloads degrade cleanly (return None) instead of raising or repeatedly
touching the filesystem.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from browser_use.browser.events import BrowserLaunchEvent
from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog


class _FakeBrowserProfile:
	"""Browser profile whose downloads directory raises on mkdir."""

	downloads_path = '\\\\\\nonsense\\\\uncreatable\\\\downloads'
	auto_download_pdfs = False


def _make_broken_watchdog() -> tuple[DownloadsWatchdog, list[str]]:
	"""Build a watchdog whose resolved downloads dir is None (launch failed)."""
	mkdir_calls: list[str] = []

	browser_session = SimpleNamespace(
		logger=SimpleNamespace(warning=lambda *a, **k: None, debug=lambda *a, **k: None, error=lambda *a, **k: None),
		is_local=True,
		id='broken-session-0001',
		browser_profile=_FakeBrowserProfile(),
		cdp_client=SimpleNamespace(send=AsyncMock()),
		session_manager=None,
	)
	event_bus = SimpleNamespace(dispatch=lambda *a, **k: None)
	wd = DownloadsWatchdog.model_construct(browser_session=browser_session, event_bus=event_bus)

	# Record any os.makedirs attempts so we can assert none happened.
	real_makedirs = __import__('os').makedirs

	def tracking_makedirs(path: str, exist_ok: bool = False) -> None:
		mkdir_calls.append(str(path))
		return real_makedirs(path, exist_ok=exist_ok)

	return wd, mkdir_calls


@pytest.mark.asyncio
async def test_download_file_from_url_skips_when_dir_unavailable(tmp_path) -> None:
	wd, mkdir_calls = _make_broken_watchdog()
	assert wd._resolved_downloads_dir is None

	# Simulate on_BrowserLaunchEvent having failed to create the directory.
	real_makedirs = __import__('os').makedirs

	def tracking_makedirs(path: str, exist_ok: bool = False) -> None:
		mkdir_calls.append(str(path))
		return real_makedirs(path, exist_ok=exist_ok)

	with (
		patch(
			'browser_use.browser.watchdogs.downloads_watchdog._ensure_downloads_directory',
			return_value=None,
		),
		patch('os.makedirs', side_effect=tracking_makedirs),
	):
		await wd.on_BrowserLaunchEvent(BrowserLaunchEvent())
		assert wd._resolved_downloads_dir is None

		result = await wd.download_file_from_url(
			url='https://example.com/report.pdf',
			target_id='FAKE_TARGET',
			content_type='application/pdf',
			suggested_filename='report.pdf',
		)

	assert result is None
	assert mkdir_calls == [], f'os.makedirs should not be called when directory unavailable: {mkdir_calls}'


@pytest.mark.asyncio
async def test_attach_to_target_skips_cdp_setup_when_dir_unavailable(tmp_path) -> None:
	wd, _ = _make_broken_watchdog()

	# Simulate on_BrowserLaunchEvent having failed to create the directory.
	with patch(
		'browser_use.browser.watchdogs.downloads_watchdog._ensure_downloads_directory',
		return_value=None,
	):
		await wd.on_BrowserLaunchEvent(BrowserLaunchEvent())

	assert wd._resolved_downloads_dir is None

	# attach_to_target must not configure CDP with the broken path.
	await wd.attach_to_target('FAKE_TARGET')

	set_download_behavior = cast(Any, wd.browser_session.cdp_client.send).Browser.setDownloadBehavior
	set_download_behavior.assert_not_called()
	assert wd._download_cdp_session_setup is False
