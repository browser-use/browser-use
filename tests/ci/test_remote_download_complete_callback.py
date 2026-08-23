"""Regression test for remote-browser download completion callbacks (issue #5132).

When a download finishes on a *remote* browser, the ``downloadProgress`` CDP
event with ``state == 'completed'`` is the only signal the
``DownloadsWatchdog`` receives. The local-browser branch calls the registered
``_download_complete_callbacks`` (via ``_track_download``), but the remote
branch used to only dispatch ``FileDownloadedEvent`` on the event bus and never
invoke the direct callbacks.

``DefaultActionWatchdog._execute_click_with_download_detection`` waits on the
``on_download_complete`` callback (an ``asyncio.Event``), so without this call
the click action blocks until ``download_complete_timeout`` (30s by default)
even though the file already finished downloading. This test drives the
``downloadProgress`` handler that ``DownloadsWatchdog.attach_to_target``
registers with the CDP client and asserts the complete callback fires.
"""

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
	"""Mimics cdp_client.register.Browser.downloadProgress and captures the handler."""

	def __init__(self) -> None:
		self.handler: Any = None

	def __call__(self, handler) -> None:
		self.handler = handler


def _make_watchdog(tmp_path) -> tuple[DownloadsWatchdog, _ProgressCapture, list[Any]]:
	"""Build a DownloadsWatchdog bound to a lightweight fake *remote* session.

	Uses ``model_construct`` to bypass pydantic validation (which requires a real
	BrowserSession / EventBus wiring that would start background tasks). We only
	stub the handful of attributes the download-completion path reads.
	"""
	progress_capture = _ProgressCapture()
	cdp_register = SimpleNamespace(
		Browser=SimpleNamespace(
			downloadProgress=progress_capture,
			downloadWillBegin=lambda h: None,
		)
	)
	cdp_client = SimpleNamespace(
		register=cdp_register,
		send=AsyncMock(),  # Browser.setDownloadBehavior is awaited in attach_to_target
	)

	browser_session = SimpleNamespace(
		logger=logging.getLogger('test.downloads_watchdog'),
		is_local=False,  # remote browser -> exercises the fixed branch
		cdp_client=cdp_client,
		browser_profile=SimpleNamespace(downloads_path=str(tmp_path), auto_download_pdfs=False),
		id='test-session-0001',
	)

	dispatched: list[Any] = []
	event_bus = SimpleNamespace(dispatch=lambda event: dispatched.append(event))

	wd = DownloadsWatchdog.model_construct(browser_session=browser_session, event_bus=event_bus)
	return wd, progress_capture, dispatched


@pytest.mark.asyncio
async def test_remote_download_complete_invokes_registered_callback(tmp_path) -> None:
	wd, progress_capture, dispatched = _make_watchdog(tmp_path)

	# Drive attach_to_target so the downloadProgress handler is registered.
	await wd.attach_to_target('FAKE_TARGET_1')
	assert progress_capture.handler is not None, 'downloadProgress handler was not registered'

	# Seed the "will begin" cache so the completed event can resolve a filename.
	wd._cdp_downloads_info['guid-123'] = {
		'url': 'https://example.com/report.pdf',
		'suggested_filename': 'report.pdf',
		'handled': False,
	}

	received: list[dict] = []
	wd.register_download_callbacks(on_complete=lambda info: received.append(info))

	# Simulate the CDP downloadProgress(completed) event for a remote browser.
	completed_event = {
		'guid': 'guid-123',
		'state': 'completed',
		'filePath': '/tmp/remote-downloads/report.pdf',
		'receivedBytes': 1024,
		'totalBytes': 1024,
	}
	progress_capture.handler(completed_event, session_id=None)
	progress_capture.handler(completed_event, session_id=None)

	assert len(received) == 1, f'expected the complete callback to fire once, got {received}'
	info = received[0]
	assert info['file_name'] == 'report.pdf'
	assert info['guid'] == 'guid-123'
	assert info['auto_download'] is False
	assert info['path'].endswith('report.pdf')
	assert info['url'] == 'https://example.com/report.pdf'
	download_events = [event for event in dispatched if isinstance(event, FileDownloadedEvent)]
	assert len(download_events) == 1


@pytest.mark.asyncio
async def test_remote_download_complete_retains_current_guid_and_prunes_old_handled(
	tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
	wd, progress_capture, _ = _make_watchdog(tmp_path)
	await wd.attach_to_target('FAKE_TARGET_2')

	monkeypatch.setattr(downloads_watchdog_module, '_MAX_CDP_DOWNLOAD_INFO_ENTRIES', 3)
	wd._cdp_downloads_info.update(
		{
			'old-handled-1': {'handled': True},
			'old-handled-2': {'handled': True},
			'active-guid': {'handled': False},
			'guid-456': {'url': 'https://example.com/data.csv', 'suggested_filename': 'data.csv', 'handled': False},
		}
	)
	wd.register_download_callbacks(on_complete=lambda info: None)

	progress_capture.handler(
		{'guid': 'guid-456', 'state': 'completed', 'filePath': '/dl/data.csv', 'receivedBytes': 4, 'totalBytes': 4},
		session_id=None,
	)

	assert 'guid-456' in wd._cdp_downloads_info
	assert wd._cdp_downloads_info['guid-456']['handled'] is True
	assert len(wd._cdp_downloads_info) == 3
	assert 'old-handled-1' not in wd._cdp_downloads_info
	assert 'old-handled-2' in wd._cdp_downloads_info
	assert 'active-guid' in wd._cdp_downloads_info
