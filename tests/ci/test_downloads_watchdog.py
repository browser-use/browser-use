import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from browser_use.browser.events import FileDownloadedEvent
from browser_use.browser.watchdogs.downloads_watchdog import (
	DownloadsWatchdog,
	_is_incomplete_download,
	_should_auto_download_network_response,
)


def test_downloads_watchdog_skips_generic_text_attachment_without_file_url():
	assert not _should_auto_download_network_response(
		url='https://www.google.com/complete/search?q=test&client=gws-wiz&xssi=t',
		content_type='text/plain',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='f.txt',
	)


def test_downloads_watchdog_keeps_pdf_network_response():
	assert _should_auto_download_network_response(
		url='https://example.com/view?id=123',
		content_type='application/pdf',
		is_pdf=True,
		is_download_attachment=False,
		suggested_filename=None,
	)


def test_downloads_watchdog_keeps_named_file_attachment():
	assert _should_auto_download_network_response(
		url='https://example.com/download?id=123',
		content_type='text/csv',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='report.csv',
	)


def test_downloads_watchdog_keeps_text_attachment_with_file_url():
	assert _should_auto_download_network_response(
		url='https://example.com/files/summary.txt?download=1',
		content_type='text/plain',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='f.txt',
	)


def test_downloads_watchdog_keeps_attachment_without_known_extension():
	assert _should_auto_download_network_response(
		url='https://example.com/download?id=123',
		content_type='application/vnd.example.custom',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='statement',
	)


class _ProgressCapture:
	def __init__(self) -> None:
		self.handler: Any = None

	def __call__(self, handler) -> None:
		self.handler = handler


class _DownloadWillBeginCapture:
	def __init__(self) -> None:
		self.handler: Any = None

	def __call__(self, handler) -> None:
		self.handler = handler


def _make_local_watchdog(tmp_path: Path):
	progress_capture = _ProgressCapture()
	will_begin_capture = _DownloadWillBeginCapture()

	cdp_register = SimpleNamespace(
		Browser=SimpleNamespace(
			downloadProgress=progress_capture,
			downloadWillBegin=will_begin_capture,
		)
	)
	cdp_client = SimpleNamespace(
		register=cdp_register,
		send=AsyncMock(),
	)

	dispatched_events: list[Any] = []
	event_bus = SimpleNamespace(dispatch=lambda event: dispatched_events.append(event))

	browser_session = SimpleNamespace(
		logger=logging.getLogger('test.downloads_watchdog'),
		is_local=True,
		cdp_client=cdp_client,
		browser_profile=SimpleNamespace(downloads_path=str(tmp_path), auto_download_pdfs=False),
		id='test-session-downloads',
	)

	wd = DownloadsWatchdog.model_construct(browser_session=browser_session, event_bus=event_bus)
	return wd, will_begin_capture, progress_capture, dispatched_events


@pytest.mark.asyncio
async def test_downloads_watchdog_ignores_partial_crdownload(tmp_path: Path, monkeypatch) -> None:
	"""Verify partial .crdownload files are ignored and not reported as completed (Issue #5515 Bug A)."""
	wd, will_begin_capture, _, dispatched_events = _make_local_watchdog(tmp_path)
	await wd.attach_to_target('FAKE_TARGET')

	callbacks_fired: list[dict] = []
	wd.register_download_callbacks(on_complete=lambda info: callbacks_fired.append(info))

	guid = 'guid-partial-001'
	will_begin_capture.handler(
		{'guid': guid, 'url': 'https://example.com/big.pdf', 'suggestedFilename': 'big.pdf'},
		session_id=None,
	)

	# Simulate Chromium creating a partial file during in-progress download
	partial_file = tmp_path / 'big.pdf.crdownload'
	partial_file.write_bytes(b'PARTIAL_CONTENT_123456789')

	assert _is_incomplete_download(partial_file) is True

	# Mock asyncio.sleep to break out after one poll iteration
	sleep_calls = 0

	async def fake_sleep(duration):
		nonlocal sleep_calls
		sleep_calls += 1
		if sleep_calls > 1:
			raise asyncio.CancelledError()

	monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

	try:
		await wd._handle_cdp_download(
			cast(Any, {'guid': guid, 'url': 'https://example.com/big.pdf', 'suggestedFilename': 'big.pdf'}),
			'FAKE_TARGET',
			None,
		)
	except asyncio.CancelledError:
		pass

	file_events = [e for e in dispatched_events if isinstance(e, FileDownloadedEvent)]
	assert len(file_events) == 0, f'Expected no FileDownloadedEvent for .crdownload, got {file_events}'
	assert len(callbacks_fired) == 0
	assert wd._cdp_downloads_info[guid]['handled'] is False


@pytest.mark.asyncio
async def test_poller_completion_followed_by_cdp_results_in_single_completion(tmp_path: Path, monkeypatch) -> None:
	"""Verify poller completion followed by CDP completed event dispatches only once (Issue #5515 Bug B)."""
	wd, will_begin_capture, progress_capture, dispatched_events = _make_local_watchdog(tmp_path)
	await wd.attach_to_target('FAKE_TARGET')

	callbacks_fired: list[dict] = []
	wd.register_download_callbacks(on_complete=lambda info: callbacks_fired.append(info))

	guid = 'guid-race-002'
	will_begin_capture.handler(
		{'guid': guid, 'url': 'https://example.com/doc.pdf', 'suggestedFilename': 'doc.pdf'},
		session_id=None,
	)

	completed_file = tmp_path / 'doc.pdf'
	completed_file.write_bytes(b'%PDF-1.5 completed pdf bytes')

	# Run one poll iteration
	monkeypatch.setattr(asyncio, 'sleep', AsyncMock())
	await wd._handle_cdp_download(
		cast(Any, {'guid': guid, 'url': 'https://example.com/doc.pdf', 'suggestedFilename': 'doc.pdf'}),
		'FAKE_TARGET',
		None,
	)

	assert wd._cdp_downloads_info[guid]['handled'] is True
	assert len(callbacks_fired) == 1
	file_events = [e for e in dispatched_events if isinstance(e, FileDownloadedEvent)]
	assert len(file_events) == 1
	assert file_events[0].file_name == 'doc.pdf'

	# Now simulate CDP downloadProgress(completed) arriving afterwards
	progress_capture.handler(
		{'guid': guid, 'state': 'completed', 'filePath': str(completed_file), 'receivedBytes': 100, 'totalBytes': 100},
		session_id=None,
	)

	# Assert no duplicate callback or event occurred
	assert len(callbacks_fired) == 1
	file_events = [e for e in dispatched_events if isinstance(e, FileDownloadedEvent)]
	assert len(file_events) == 1


@pytest.mark.asyncio
async def test_cdp_completion_followed_by_poller_results_in_single_completion(tmp_path: Path, monkeypatch) -> None:
	"""Verify CDP completed event followed by poller execution dispatches only once."""
	wd, will_begin_capture, progress_capture, dispatched_events = _make_local_watchdog(tmp_path)
	await wd.attach_to_target('FAKE_TARGET')

	callbacks_fired: list[dict] = []
	wd.register_download_callbacks(on_complete=lambda info: callbacks_fired.append(info))

	guid = 'guid-cdp-first-003'
	will_begin_capture.handler(
		{'guid': guid, 'url': 'https://example.com/sheet.xlsx', 'suggestedFilename': 'sheet.xlsx'},
		session_id=None,
	)

	completed_file = tmp_path / 'sheet.xlsx'
	completed_file.write_bytes(b'PK\x03\x04 fake xlsx content')

	# CDP completed arrives first
	progress_capture.handler(
		{'guid': guid, 'state': 'completed', 'filePath': str(completed_file), 'receivedBytes': 50, 'totalBytes': 50},
		session_id=None,
	)

	assert wd._cdp_downloads_info[guid]['handled'] is True
	assert len(callbacks_fired) == 1
	file_events = [e for e in dispatched_events if isinstance(e, FileDownloadedEvent)]
	assert len(file_events) == 1

	# Now poller runs
	monkeypatch.setattr(asyncio, 'sleep', AsyncMock())
	await wd._handle_cdp_download(
		cast(Any, {'guid': guid, 'url': 'https://example.com/sheet.xlsx', 'suggestedFilename': 'sheet.xlsx'}),
		'FAKE_TARGET',
		None,
	)

	# Poller should have exited early seeing handled=True
	assert len(callbacks_fired) == 1
	file_events = [e for e in dispatched_events if isinstance(e, FileDownloadedEvent)]
	assert len(file_events) == 1


@pytest.mark.asyncio
async def test_normal_download_local_with_filepath(tmp_path: Path) -> None:
	"""Verify normal local download flow with filePath dispatches exactly once."""
	wd, will_begin_capture, progress_capture, dispatched_events = _make_local_watchdog(tmp_path)
	await wd.attach_to_target('FAKE_TARGET')

	callbacks_fired: list[dict] = []
	wd.register_download_callbacks(on_complete=lambda info: callbacks_fired.append(info))

	guid = 'guid-normal-004'
	will_begin_capture.handler(
		{'guid': guid, 'url': 'https://example.com/readme.txt', 'suggestedFilename': 'readme.txt'},
		session_id=None,
	)

	txt_file = tmp_path / 'readme.txt'
	txt_file.write_text('Hello, world!')

	progress_capture.handler(
		{'guid': guid, 'state': 'completed', 'filePath': str(txt_file), 'receivedBytes': 13, 'totalBytes': 13},
		session_id=None,
	)

	assert wd._cdp_downloads_info[guid]['handled'] is True
	assert len(callbacks_fired) == 1
	assert callbacks_fired[0]['file_name'] == 'readme.txt'
	assert callbacks_fired[0]['file_size'] == 13
	file_events = [e for e in dispatched_events if isinstance(e, FileDownloadedEvent)]
	assert len(file_events) == 1
	assert file_events[0].file_name == 'readme.txt'


@pytest.mark.asyncio
async def test_failed_track_download_does_not_suppress_subsequent_completion(tmp_path: Path) -> None:
	"""Verify a non-existent path in _track_download returns False and does not mark handled."""
	wd, will_begin_capture, _, dispatched_events = _make_local_watchdog(tmp_path)
	await wd.attach_to_target('FAKE_TARGET')

	guid = 'guid-retry-005'
	will_begin_capture.handler(
		{'guid': guid, 'url': 'https://example.com/retry.zip', 'suggestedFilename': 'retry.zip'},
		session_id=None,
	)

	# Attempt tracking non-existent file
	res = wd._track_download(str(tmp_path / 'does_not_exist.zip'), guid=guid)
	assert res is False
	assert wd._cdp_downloads_info[guid]['handled'] is False
	file_events = [e for e in dispatched_events if isinstance(e, FileDownloadedEvent)]
	assert len(file_events) == 0

	# Now file actually exists
	real_file = tmp_path / 'retry.zip'
	real_file.write_bytes(b'PK\x03\x04 zip data')

	res_success = wd._track_download(str(real_file), guid=guid)
	assert res_success is True
	file_events = [e for e in dispatched_events if isinstance(e, FileDownloadedEvent)]
	assert len(file_events) == 1
	assert file_events[0].file_name == 'retry.zip'


@pytest.mark.asyncio
async def test_downloads_watchdog_fallback_ignores_partial_crdownload(tmp_path: Path) -> None:
	"""Verify CDP completed fallback (filePath=None) ignores in-progress .crdownload files."""
	wd, will_begin_capture, progress_capture, dispatched_events = _make_local_watchdog(tmp_path)
	await wd.attach_to_target('FAKE_TARGET')

	callbacks_fired: list[dict] = []
	wd.register_download_callbacks(on_complete=lambda info: callbacks_fired.append(info))

	guid = 'guid-fallback-crdownload-006'
	will_begin_capture.handler(
		{'guid': guid, 'url': 'https://example.com/stream.mp4', 'suggestedFilename': 'stream.mp4'},
		session_id=None,
	)

	# In-progress partial file created in downloads directory
	partial_file = tmp_path / 'stream.mp4.crdownload'
	partial_file.write_bytes(b'STREAM_PARTIAL_BYTES_12345')

	# CDP completed event arrives without filePath (triggers fallback directory scan)
	progress_capture.handler(
		{'guid': guid, 'state': 'completed', 'filePath': None, 'receivedBytes': 26, 'totalBytes': 100},
		session_id=None,
	)

	file_events = [e for e in dispatched_events if isinstance(e, FileDownloadedEvent)]
	assert len(file_events) == 0, f'Expected no FileDownloadedEvent for .crdownload in fallback, got {file_events}'
	assert len(callbacks_fired) == 0
	assert wd._cdp_downloads_info[guid]['handled'] is False
