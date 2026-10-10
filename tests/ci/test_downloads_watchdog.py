"""Regression tests for DownloadsWatchdog network monitoring setup.

``DownloadsWatchdog.attach_to_target`` configures two independent layers:

1. Browser-level CDP download handling (``Browser.setDownloadBehavior`` +
   ``Browser.downloadWillBegin`` / ``Browser.downloadProgress`` handlers),
   which must only ever be set up once per browser session.
2. Per-target Network monitoring (``Network.enable`` on the target's CDP
   session + a single global ``Network.responseReceived`` callback), which
   must run for *every* eligible tab.

A previous early ``return`` in ``attach_to_target`` (guarded by
``_download_cdp_session_setup``) skipped the per-target Network monitoring
for every tab after the first one, so downloads/PDFs on the second tab were
never detected. These tests drive ``attach_to_target`` against a mocked CDP
client and assert the observable CDP calls.
"""

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import browser_use.browser.watchdogs.downloads_watchdog as downloads_watchdog_module
from browser_use.browser.watchdogs.downloads_watchdog import (
	DownloadsWatchdog,
	_should_auto_download_network_response,
)


class _HandlerCapture:
	"""Mimics a cdp_client.register.* slot and records every registered handler."""

	def __init__(self) -> None:
		self.handlers: list[Any] = []

	def __call__(self, handler) -> None:
		self.handlers.append(handler)


class _FakeCdpRig:
	"""Fake browser session + CDP client capturing all download/network CDP calls."""

	def __init__(self, tmp_path, auto_download_pdfs: bool = True) -> None:
		self.download_will_begin = _HandlerCapture()
		self.download_progress = _HandlerCapture()
		self.network_response_received = _HandlerCapture()
		self.set_download_behavior = AsyncMock()
		self.network_enable = AsyncMock()

		cdp_client = SimpleNamespace(
			register=SimpleNamespace(
				Browser=SimpleNamespace(
					downloadWillBegin=self.download_will_begin,
					downloadProgress=self.download_progress,
				),
				Network=SimpleNamespace(responseReceived=self.network_response_received),
			),
			send=SimpleNamespace(
				Browser=SimpleNamespace(setDownloadBehavior=self.set_download_behavior),
				Network=SimpleNamespace(enable=self.network_enable),
			),
		)

		self._sessions: dict[str, SimpleNamespace] = {}

		async def get_or_create_cdp_session(target_id, focus=False):
			if target_id not in self._sessions:
				self._sessions[target_id] = SimpleNamespace(session_id=f'session-for-{target_id}')
			return self._sessions[target_id]

		browser_session = SimpleNamespace(
			logger=logging.getLogger('test.downloads_watchdog'),
			is_local=True,
			cdp_client=cdp_client,
			browser_profile=SimpleNamespace(downloads_path=str(tmp_path), auto_download_pdfs=auto_download_pdfs),
			get_or_create_cdp_session=get_or_create_cdp_session,
			id='test-session-0001',
		)

		# Real EventBus.dispatch() schedules async handler tasks; we only assert
		# on direct CDP calls here, so stub dispatch() to a no-op.
		event_bus = SimpleNamespace(dispatch=lambda *a, **k: None)

		self.watchdog = DownloadsWatchdog.model_construct(browser_session=browser_session, event_bus=event_bus)

	def enabled_session_ids(self) -> list[str]:
		return [call.kwargs['session_id'] for call in self.network_enable.await_args_list]


async def test_second_tab_gets_network_monitoring(tmp_path) -> None:
	"""Network.enable must be called for every attached tab, not just the first.

	Regression: the early return guarded by ``_download_cdp_session_setup``
	skipped ``_setup_network_monitoring`` for all tabs after the first one, so
	downloads/PDFs on the second tab were never detected.
	"""
	rig = _FakeCdpRig(tmp_path)

	await rig.watchdog.attach_to_target('TARGET_1')
	await rig.watchdog.attach_to_target('TARGET_2')

	assert rig.enabled_session_ids() == ['session-for-TARGET_1', 'session-for-TARGET_2']
	assert rig.watchdog._network_monitored_targets == {'TARGET_1', 'TARGET_2'}


async def test_browser_download_handlers_set_only_once_across_tabs(tmp_path) -> None:
	"""Browser-level download setup must stay idempotent across repeated attachment."""
	rig = _FakeCdpRig(tmp_path)

	await rig.watchdog.attach_to_target('TARGET_1')
	await rig.watchdog.attach_to_target('TARGET_2')
	await rig.watchdog.attach_to_target('TARGET_1')  # repeated attachment of the same tab

	assert rig.set_download_behavior.await_count == 1, 'Browser.setDownloadBehavior must be called exactly once'
	assert len(rig.download_will_begin.handlers) == 1, 'downloadWillBegin handler must be registered exactly once'
	assert len(rig.download_progress.handlers) == 1, 'downloadProgress handler must be registered exactly once'
	assert len(rig.network_response_received.handlers) == 1, (
		'global Network.responseReceived callback must be registered exactly once'
	)
	# Repeated attachment of the same tab must not re-enable Network either
	assert rig.enabled_session_ids() == ['session-for-TARGET_1', 'session-for-TARGET_2']


async def test_network_monitoring_skipped_when_auto_download_disabled(tmp_path) -> None:
	"""With auto_download_pdfs disabled, no per-target Network monitoring is set up."""
	rig = _FakeCdpRig(tmp_path, auto_download_pdfs=False)

	await rig.watchdog.attach_to_target('TARGET_1')
	await rig.watchdog.attach_to_target('TARGET_2')

	assert rig.network_enable.await_count == 0, 'Network.enable must not be called when auto-download is disabled'
	assert rig.network_response_received.handlers == [], 'network callback must not be registered when disabled'
	# Browser-level download handling is still set up once
	assert rig.set_download_behavior.await_count == 1
	assert len(rig.download_will_begin.handlers) == 1


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


def test_downloads_watchdog_keeps_named_file_attachment_as_network_fallback_candidate():
	assert _should_auto_download_network_response(
		url='https://example.com/download?id=123',
		content_type='text/csv',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='report.csv',
	)


def test_downloads_watchdog_keeps_text_attachment_with_file_url_as_network_fallback_candidate():
	assert _should_auto_download_network_response(
		url='https://example.com/files/summary.txt?download=1',
		content_type='text/plain',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='f.txt',
	)


def test_downloads_watchdog_keeps_attachment_without_known_extension_as_network_fallback_candidate():
	assert _should_auto_download_network_response(
		url='https://example.com/download?id=123',
		content_type='application/vnd.example.custom',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='statement',
	)


def test_downloads_watchdog_keeps_pdf_attachment_as_network_fallback_candidate():
	assert _should_auto_download_network_response(
		url='https://example.com/document.pdf',
		content_type='application/pdf',
		is_pdf=True,
		is_download_attachment=True,
		suggested_filename='document.pdf',
	)


def test_downloads_watchdog_uses_network_for_attachment_if_browser_download_events_unavailable():
	assert _should_auto_download_network_response(
		url='https://example.com/download?id=123',
		content_type='application/zip',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='archive.zip',
	)


async def test_network_fallback_stops_when_cdp_completes(tmp_path) -> None:
	rig = _FakeCdpRig(tmp_path)
	url = 'https://example.com/archive.zip'
	rig.watchdog._cdp_downloads_info['guid-1'] = {'url': url, 'handled': False}

	waiter = asyncio.create_task(rig.watchdog._cdp_handled_or_claim_network(url))
	await asyncio.sleep(0)
	assert rig.watchdog._claim_cdp_download('guid-1')
	rig.watchdog._mark_cdp_download_handled('guid-1')

	assert await waiter is False
	assert rig.watchdog._download_owners[url] == 'cdp'


async def test_network_fallback_observes_cdp_completion_before_task_starts(tmp_path) -> None:
	rig = _FakeCdpRig(tmp_path)
	url = 'https://example.com/archive.zip'
	rig.watchdog._download_completion_events[url] = asyncio.Event()
	rig.watchdog._download_owners[url] = 'waiting'
	rig.watchdog._cdp_downloads_info['guid-1'] = {'url': url, 'handled': False}

	assert rig.watchdog._claim_cdp_download('guid-1')
	rig.watchdog._mark_cdp_download_handled('guid-1')
	del rig.watchdog._cdp_downloads_info['guid-1']  # remote completion cleanup

	assert await rig.watchdog._cdp_handled_or_claim_network(url) is False


async def test_network_fallback_runs_after_cdp_timeout(tmp_path, monkeypatch) -> None:
	rig = _FakeCdpRig(tmp_path)
	url = 'https://example.com/archive.zip'
	monkeypatch.setattr(downloads_watchdog_module, '_CDP_DOWNLOAD_FALLBACK_TIMEOUT', 0)

	assert await rig.watchdog._cdp_handled_or_claim_network(url) is True
	assert rig.watchdog._download_owners[url] == 'network'


def test_cdp_does_not_dispatch_after_network_fallback_claims_download(tmp_path) -> None:
	rig = _FakeCdpRig(tmp_path)
	url = 'https://example.com/archive.zip'
	rig.watchdog._cdp_downloads_info['guid-1'] = {'url': url, 'handled': False}
	rig.watchdog._download_owners[url] = 'network'

	assert not rig.watchdog._claim_cdp_download('guid-1')
