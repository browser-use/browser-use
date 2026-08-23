from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from cdp_use.cdp.browser import DownloadProgressEvent as CDPDownloadProgressEvent

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import FileDownloadedEvent
from browser_use.browser.watchdogs import downloads_watchdog as downloads_watchdog_module
from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog


@pytest.fixture
async def download_watchdog(
	tmp_path: Path,
) -> AsyncIterator[tuple[DownloadsWatchdog, BrowserSession, list[FileDownloadedEvent]]]:
	"""Build the watchdog with the repository's real BrowserSession and event bus."""
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			downloads_path=str(tmp_path),
			headless=True,
			user_data_dir=None,
		)
	)
	watchdog = DownloadsWatchdog(browser_session=browser_session, event_bus=browser_session.event_bus)
	downloaded_events: list[FileDownloadedEvent] = []

	def collect_download(event: FileDownloadedEvent) -> None:
		downloaded_events.append(event)

	browser_session.event_bus.on(FileDownloadedEvent, collect_download)
	try:
		yield watchdog, browser_session, downloaded_events
	finally:
		await browser_session.event_bus.stop(clear=True, timeout=1)


class _Clock:
	def __init__(self) -> None:
		self.value = 0.0

	def time(self) -> float:
		return self.value

	async def advance(self, seconds: float) -> None:
		self.value += seconds


async def _run_filesystem_poller(
	watchdog: DownloadsWatchdog,
	guid: str,
	filename: str,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	clock = _Clock()
	with monkeypatch.context() as patch:
		patch.setattr(downloads_watchdog_module.asyncio, 'get_event_loop', lambda: clock)
		patch.setattr(downloads_watchdog_module.asyncio, 'sleep', clock.advance)
		await watchdog._handle_cdp_download(
			{
				'guid': guid,
				'url': f'https://example.com/{filename}',
				'suggestedFilename': filename,
				'frameId': 'FRAME-1',
			},
			'FAKE_TARGET',
			None,
		)


@pytest.mark.asyncio
async def test_poller_completion_notifies_once_when_progress_arrives_later(
	download_watchdog: tuple[DownloadsWatchdog, BrowserSession, list[FileDownloadedEvent]],
	tmp_path: Path,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	watchdog, browser_session, downloaded_events = download_watchdog
	downloaded_file = tmp_path / 'report.pdf'
	downloaded_file.write_bytes(b'complete download')
	watchdog._cdp_downloads_info['guid-123'] = {
		'url': 'https://example.com/report.pdf',
		'suggested_filename': 'report.pdf',
		'handled': False,
	}
	completed: list[dict[str, Any]] = []
	watchdog.register_download_callbacks(on_complete=lambda info: completed.append(info))

	await _run_filesystem_poller(watchdog, 'guid-123', 'report.pdf', monkeypatch)

	watchdog._on_cdp_download_progress(
		{
			'guid': 'guid-123',
			'state': 'completed',
			'filePath': str(downloaded_file),
			'receivedBytes': downloaded_file.stat().st_size,
			'totalBytes': downloaded_file.stat().st_size,
		},
		None,
	)
	await browser_session.event_bus.wait_until_idle(timeout=1)

	assert watchdog._cdp_downloads_info['guid-123']['handled'] is True
	assert len(completed) == 1
	assert completed[0]['guid'] == 'guid-123'
	assert completed[0]['url'] == 'https://example.com/report.pdf'
	assert len(downloaded_events) == 1
	assert downloaded_events[0].guid == 'guid-123'
	assert downloaded_events[0].url == 'https://example.com/report.pdf'


@pytest.mark.asyncio
async def test_progress_file_path_preserves_source_url_and_notifies_once(
	download_watchdog: tuple[DownloadsWatchdog, BrowserSession, list[FileDownloadedEvent]],
	tmp_path: Path,
) -> None:
	watchdog, browser_session, downloaded_events = download_watchdog
	downloaded_file = tmp_path / 'progress-first.pdf'
	downloaded_file.write_bytes(b'complete download')
	source_url = 'https://example.com/progress-first.pdf'
	watchdog._cdp_downloads_info['guid-file-path'] = {
		'url': source_url,
		'suggested_filename': downloaded_file.name,
		'handled': False,
	}
	completed: list[dict[str, Any]] = []
	watchdog.register_download_callbacks(on_complete=lambda info: completed.append(info))
	completed_event: CDPDownloadProgressEvent = {
		'guid': 'guid-file-path',
		'state': 'completed',
		'filePath': str(downloaded_file),
		'receivedBytes': downloaded_file.stat().st_size,
		'totalBytes': downloaded_file.stat().st_size,
	}

	watchdog._on_cdp_download_progress(completed_event, None)
	watchdog._on_cdp_download_progress(completed_event, None)
	await browser_session.event_bus.wait_until_idle(timeout=1)

	assert watchdog._cdp_downloads_info['guid-file-path']['handled'] is True
	assert len(completed) == 1
	assert completed[0]['url'] == source_url
	assert len(downloaded_events) == 1
	assert downloaded_events[0].url == source_url


@pytest.mark.asyncio
async def test_progress_filesystem_fallback_preserves_url_without_claiming_another_file(
	download_watchdog: tuple[DownloadsWatchdog, BrowserSession, list[FileDownloadedEvent]],
	tmp_path: Path,
) -> None:
	watchdog, browser_session, downloaded_events = download_watchdog
	downloaded_file = tmp_path / 'fallback-first.csv'
	downloaded_file.write_bytes(b'complete download')
	source_url = 'https://example.com/fallback-first.csv'
	watchdog._cdp_downloads_info['guid-no-file-path'] = {
		'url': source_url,
		'suggested_filename': downloaded_file.name,
		'handled': False,
	}
	completed: list[dict[str, Any]] = []
	watchdog.register_download_callbacks(on_complete=lambda info: completed.append(info))
	completed_event: CDPDownloadProgressEvent = {
		'guid': 'guid-no-file-path',
		'state': 'completed',
		'receivedBytes': downloaded_file.stat().st_size,
		'totalBytes': downloaded_file.stat().st_size,
	}

	watchdog._on_cdp_download_progress(completed_event, None)
	await browser_session.event_bus.wait_until_idle(timeout=1)

	# A later duplicate must return before scanning and claiming an unrelated file.
	unrelated_file = tmp_path / 'other-download.txt'
	unrelated_file.write_bytes(b'another complete download')
	watchdog._on_cdp_download_progress(completed_event, None)
	await browser_session.event_bus.wait_until_idle(timeout=1)

	assert watchdog._cdp_downloads_info['guid-no-file-path']['handled'] is True
	assert downloaded_file.name in watchdog._initial_downloads_snapshot
	assert unrelated_file.name not in watchdog._initial_downloads_snapshot
	assert len(completed) == 1
	assert completed[0]['url'] == source_url
	assert len(downloaded_events) == 1
	assert downloaded_events[0].url == source_url


@pytest.mark.asyncio
@pytest.mark.parametrize('suffix', ['.crdownload', '.part', '.tmp'])
async def test_cdp_fallbacks_ignore_partial_download_files(
	download_watchdog: tuple[DownloadsWatchdog, BrowserSession, list[FileDownloadedEvent]],
	tmp_path: Path,
	monkeypatch: pytest.MonkeyPatch,
	suffix: str,
) -> None:
	watchdog, browser_session, downloaded_events = download_watchdog
	partial_file = tmp_path / f'report.pdf{suffix}'
	partial_file.write_bytes(b'incomplete download')
	watchdog._cdp_downloads_info['guid-456'] = {
		'url': 'https://example.com/report.pdf',
		'suggested_filename': 'report.pdf',
		'handled': False,
	}

	await _run_filesystem_poller(watchdog, 'guid-456', 'report.pdf', monkeypatch)

	# Exercise the no-filePath progress fallback against the same partial file.
	watchdog._on_cdp_download_progress(
		{
			'guid': 'guid-456',
			'state': 'completed',
			'receivedBytes': partial_file.stat().st_size,
			'totalBytes': partial_file.stat().st_size,
		},
		None,
	)
	await browser_session.event_bus.wait_until_idle(timeout=1)

	assert downloaded_events == []
	assert watchdog._cdp_downloads_info['guid-456']['handled'] is False
