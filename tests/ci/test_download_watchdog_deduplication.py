from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from browser_use.browser.events import FileDownloadedEvent
from browser_use.browser.watchdogs import downloads_watchdog as downloads_watchdog_module
from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog


class _ProgressCapture:
	def __init__(self) -> None:
		self.handler: Any = None

	def __call__(self, handler: Any) -> None:
		self.handler = handler


class _EventCapture:
	def __init__(self) -> None:
		self.events: list[Any] = []

	def dispatch(self, event: Any) -> None:
		self.events.append(event)


def _make_watchdog(tmp_path) -> tuple[DownloadsWatchdog, _ProgressCapture, _EventCapture]:
	progress_capture = _ProgressCapture()
	cdp_client = SimpleNamespace(
		register=SimpleNamespace(
			Browser=SimpleNamespace(
				downloadProgress=progress_capture,
				downloadWillBegin=lambda handler: None,
			)
		),
		send=AsyncMock(),
	)
	browser_session = SimpleNamespace(
		logger=logging.getLogger('test.downloads_watchdog.deduplication'),
		is_local=True,
		cdp_client=cdp_client,
		browser_profile=SimpleNamespace(downloads_path=str(tmp_path), auto_download_pdfs=False),
		id='test-session-0001',
	)
	event_capture = _EventCapture()
	watchdog = DownloadsWatchdog.model_construct(browser_session=browser_session, event_bus=event_capture)
	return watchdog, progress_capture, event_capture


@pytest.mark.asyncio
async def test_completed_progress_does_not_redispatch_handled_download(tmp_path) -> None:
	watchdog, progress_capture, event_capture = _make_watchdog(tmp_path)
	await watchdog.attach_to_target('FAKE_TARGET')

	downloaded_file = tmp_path / 'report.pdf'
	downloaded_file.write_bytes(b'complete download')
	watchdog._cdp_downloads_info['guid-123'] = {
		'url': 'https://example.com/report.pdf',
		'suggested_filename': 'report.pdf',
		'handled': True,
	}
	completed: list[dict[str, Any]] = []
	watchdog.register_download_callbacks(on_complete=lambda info: completed.append(info))

	progress_capture.handler(
		{
			'guid': 'guid-123',
			'state': 'completed',
			'filePath': str(downloaded_file),
			'receivedBytes': downloaded_file.stat().st_size,
			'totalBytes': downloaded_file.stat().st_size,
		},
		session_id=None,
	)

	assert completed == []
	assert not any(isinstance(event, FileDownloadedEvent) for event in event_capture.events)


@pytest.mark.asyncio
async def test_cdp_poller_ignores_partial_download_files(tmp_path, monkeypatch) -> None:
	watchdog, _, event_capture = _make_watchdog(tmp_path)
	partial_file = tmp_path / 'report.pdf.crdownload'
	partial_file.write_bytes(b'incomplete download')
	watchdog._cdp_downloads_info['guid-456'] = {
		'url': 'https://example.com/report.pdf',
		'suggested_filename': 'report.pdf',
		'handled': False,
	}

	class _Clock:
		value = 0.0

		def time(self) -> float:
			return self.value

	clock = _Clock()

	async def advance_clock(seconds: float) -> None:
		clock.value += seconds

	monkeypatch.setattr(downloads_watchdog_module.asyncio, 'get_event_loop', lambda: clock)
	monkeypatch.setattr(downloads_watchdog_module.asyncio, 'sleep', advance_clock)

	await watchdog._handle_cdp_download(
		{
			'guid': 'guid-456',
			'url': 'https://example.com/report.pdf',
			'suggestedFilename': 'report.pdf',
			'frameId': 'FRAME-1',
		},
		'FAKE_TARGET',
		None,
	)

	assert not any(isinstance(event, FileDownloadedEvent) for event in event_capture.events)
	assert watchdog._cdp_downloads_info['guid-456']['handled'] is False
