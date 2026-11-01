"""Regression tests: Network.responseReceived must reach both the Downloads and HAR watchdogs.

cdp-use's event registry is single-slot per CDP method (the last registration for a
method silently replaces the previous one). DownloadsWatchdog and
HarRecordingWatchdog both need Network.responseReceived on the shared root CDP
client, so they must not register directly — SessionManager fans the event out to
subscribed listeners instead.
"""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from cdp_use.cdp.network.events import RequestWillBeSentEvent

from browser_use.browser.events import BrowserConnectedEvent, BrowserStoppedEvent, BrowserStopEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.session_manager import SessionManager
from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog
from browser_use.browser.watchdogs.har_recording_watchdog import HarRecordingWatchdog


class _DomainSlot:
	"""Attribute surface mimicking cdp_use's register.<Domain>.<Method>."""

	def __init__(self, registry: '_SingleSlotRegistry', domain: str) -> None:
		self._registry = registry
		self._domain = domain

	def __getattr__(self, method: str) -> Any:
		def _register(handler: Any) -> None:
			# Single slot: the last registration for a method wins, exactly like cdp-use.
			self._registry.handlers[f'{self._domain}.{method}'] = handler

		return _register


class _SingleSlotRegistry:
	"""Stands in for cdp-use's EventRegistry: one handler slot per 'Domain.method'."""

	def __init__(self) -> None:
		self.handlers: dict[str, Any] = {}

	def __getattr__(self, domain: str) -> _DomainSlot:
		return _DomainSlot(self, domain)


class _FakeCdpClient:
	def __init__(self) -> None:
		self.register = _SingleSlotRegistry()
		self.send = Mock()
		self.send.Browser.getVersion = AsyncMock(return_value={})
		self.send.Browser.setDownloadBehavior = AsyncMock()
		self.send.Network.enable = AsyncMock()
		self.send.Page.enable = AsyncMock()
		self.send.Target.setDiscoverTargets = AsyncMock()
		self.send.Target.setAutoAttach = AsyncMock()


async def _make_session(tmp_path, monkeypatch) -> tuple[BrowserSession, SessionManager, _FakeCdpClient]:
	session = BrowserSession(
		browser_profile=BrowserProfile(
			downloads_path=tmp_path / 'downloads',
			record_har_path=tmp_path / 'session.har',
		)
	)
	fake_client = _FakeCdpClient()
	session._cdp_client_root = fake_client  # type: ignore[assignment]

	manager = SessionManager(session)
	session.session_manager = manager

	# start_monitoring() otherwise performs real target discovery over CDP.
	monkeypatch.setattr(SessionManager, '_initialize_existing_targets', AsyncMock())
	# Both watchdogs resolve CDP sessions through this entry point.
	monkeypatch.setattr(
		BrowserSession,
		'get_or_create_cdp_session',
		AsyncMock(return_value=SimpleNamespace(cdp_client=fake_client, session_id='test-session', target_id='AAAA1111')),
	)
	await manager.start_monitoring()
	return session, manager, fake_client


async def test_response_received_reaches_downloads_and_har_watchdogs(tmp_path, monkeypatch):
	"""With downloads_path + record_har_path both configured, a responseReceived event
	must trigger PDF auto-download detection AND be recorded in the HAR entries.

	Before the multicast fix, HAR registered last and clobbered the downloads handler
	in cdp-use's single-slot registry, silently disabling PDF auto-download detection.
	"""
	session, manager, fake_client = await _make_session(tmp_path, monkeypatch)

	downloads = DownloadsWatchdog(event_bus=session.event_bus, browser_session=session)
	await downloads.attach_to_target('AAAA1111')
	assert 'AAAA1111' in downloads._network_monitored_targets

	har = HarRecordingWatchdog(event_bus=session.event_bus, browser_session=session)
	await har.on_BrowserConnectedEvent(BrowserConnectedEvent(cdp_url='ws://localhost:9222'))
	assert har._enabled

	# Both handlers coexist via the SessionManager multicast...
	assert downloads._response_received_listener in manager._response_received_listeners
	assert har._response_received_listener in manager._response_received_listeners
	# ...and the single-slot registry keeps exactly one fan-out handler, not either
	# watchdog's handler overwriting the other.
	fan_out = fake_client.register.handlers['Network.responseReceived']
	assert fan_out is not downloads._response_received_listener
	assert fan_out is not har._response_received_listener

	# Dispatch a PDF response through the real global handler: both watchdogs must react.
	manager._session_to_target['test-session'] = 'AAAA1111'
	request_params = cast(
		RequestWillBeSentEvent,
		{'requestId': 'req-1', 'request': {'url': 'https://example.com/report.pdf', 'method': 'GET'}},
	)
	har._on_request_will_be_sent(request_params, 'test-session')
	download_mock = AsyncMock(return_value=None)
	monkeypatch.setattr(DownloadsWatchdog, 'download_file_from_url', download_mock)
	fan_out(
		{
			'requestId': 'req-1',
			'type': 'Document',
			'response': {
				'url': 'https://example.com/report.pdf',
				'status': 200,
				'mimeType': 'application/pdf',
				'headers': {},
			},
		},
		'test-session',
	)

	assert har._entries['req-1'].status == 200, 'HAR watchdog did not receive responseReceived'
	assert 'https://example.com/report.pdf' in downloads._detected_downloads, (
		'downloads watchdog did not receive responseReceived (PDF auto-download detection was clobbered)'
	)
	if downloads._cdp_event_tasks:
		await asyncio.gather(*downloads._cdp_event_tasks)
	download_mock.assert_awaited_once()


async def test_response_received_listeners_removed_on_stop(tmp_path, monkeypatch):
	"""Teardown must unsubscribe both watchdogs from the multicast."""
	session, manager, fake_client = await _make_session(tmp_path, monkeypatch)

	downloads = DownloadsWatchdog(event_bus=session.event_bus, browser_session=session)
	await downloads.attach_to_target('AAAA1111')

	har = HarRecordingWatchdog(event_bus=session.event_bus, browser_session=session)
	await har.on_BrowserConnectedEvent(BrowserConnectedEvent(cdp_url='ws://localhost:9222'))
	assert len(manager._response_received_listeners) == 2

	await downloads.on_BrowserStoppedEvent(BrowserStoppedEvent())
	await har.on_BrowserStopEvent(BrowserStopEvent())

	assert not manager._response_received_listeners
	assert not downloads._network_callback_registered
	assert har._response_received_manager is None
