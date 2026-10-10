"""
Test that watchdogs keep working after the CDP WebSocket drops and auto-reconnects.

reconnect() replaces the CDP client, and cdp-use event handlers live on the client, so
every watchdog that registered CDP handlers has to register them again on the new one.

Usage:
	uv run pytest -vxs tests/ci/browser/test_reconnect_watchdogs.py
"""

import asyncio
import threading

import pytest
from pytest_httpserver import HTTPServer
from werkzeug import Response

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import (
	BrowserReconnectedEvent,
	CaptchaSolverStartedEvent,
	FileDownloadedEvent,
	NavigateToUrlEvent,
)


@pytest.fixture
async def browser_session(tmp_path):
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			downloads_path=str(tmp_path / 'downloads'),
		)
	)
	await session.start()
	yield session
	await session.kill()


async def _drop_websocket_and_reconnect(browser_session: BrowserSession) -> None:
	"""Close the live CDP WebSocket and wait until auto-reconnect and its handlers finish."""
	old_client = browser_session._cdp_client_root
	assert old_client is not None and old_client.ws is not None
	reconnected = asyncio.ensure_future(browser_session.event_bus.expect(BrowserReconnectedEvent, timeout=30))
	await old_client.ws.close()
	event = await reconnected
	await event  # wait for every BrowserReconnectedEvent handler to finish
	assert browser_session._cdp_client_root is not old_client


async def _evaluate(browser_session: BrowserSession, expression: str, target_id: str | None = None):
	if target_id is None:
		cdp_session = await browser_session.get_or_create_cdp_session()
	else:
		cdp_session = await browser_session.get_or_create_cdp_session(target_id, focus=False)
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': expression, 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	return result.get('result', {}).get('value')


async def _drop_websocket_with_alert_open(
	browser_session: BrowserSession, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, target_id: str
) -> bool:
	"""Close the CDP WebSocket, open alert() in a visible tab while no client is connected, then let
	auto-reconnect run. Returns whether reconnect and its handlers finished within 15 s."""
	go = threading.Event()
	dialog_opening = threading.Event()
	alert_returned = threading.Event()

	def record(signal: threading.Event):
		def handler(request):
			signal.set()
			return Response('')

		return handler

	httpserver.expect_request('/go').respond_with_handler(lambda request: Response('go' if go.is_set() else 'wait'))
	httpserver.expect_request('/dialog-opening').respond_with_handler(record(dialog_opening))
	httpserver.expect_request('/alert-returned').respond_with_handler(record(alert_returned))

	# alert() only blocks a visible tab; Chrome doesn't show one from a hidden tab.
	assert await _evaluate(browser_session, 'document.visibilityState', target_id=target_id) == 'visible'

	# The tab opens alert() only after the WebSocket is closed, and signals just before it.
	await _evaluate(
		browser_session,
		"""const poll = setInterval(async () => {
			if ((await (await fetch('/go')).text()) !== 'go') return;
			clearInterval(poll);
			navigator.sendBeacon('/dialog-opening');
			alert('opened while the CDP WebSocket was down');
			navigator.sendBeacon('/alert-returned');
		}, 20)""",
		target_id=target_id,
	)

	# Hold reconnect() until that alert() is opening, so no CDP client is connected when it opens.
	reconnect = BrowserSession.reconnect
	release = asyncio.Event()

	async def reconnect_after_release(self: BrowserSession) -> None:
		await release.wait()
		await reconnect(self)

	monkeypatch.setattr(BrowserSession, 'reconnect', reconnect_after_release)

	old_client = browser_session._cdp_client_root
	assert old_client is not None and old_client.ws is not None
	reconnected = asyncio.ensure_future(browser_session.event_bus.expect(BrowserReconnectedEvent, timeout=30))
	try:
		await old_client.ws.close()
		go.set()
		assert await asyncio.to_thread(dialog_opening.wait, 10), 'the page never opened its alert()'
		release.set()

		async def reconnect_handled() -> None:
			# expect() registers its handler after the watchdogs' and the bus runs handlers one at a time,
			# so it resolves only once their BrowserReconnectedEvent handlers have returned.
			event = await reconnected
			await event

		try:
			await asyncio.wait_for(reconnect_handled(), timeout=15)
			finished = True
		except TimeoutError:
			finished = False
	finally:
		release.set()
		reconnected.cancel()
	assert not alert_returned.is_set(), 'alert() did not block the tab, so it was not open across the drop'
	return finished


async def test_alert_is_dismissed_after_reconnect(browser_session: BrowserSession, httpserver: HTTPServer):
	"""PopupsWatchdog registers its dialog handler on the client created by reconnect()."""
	httpserver.expect_request('/dialog').respond_with_data(
		'<html><head><title>Dialog</title></head><body><h1>Dialog page</h1></body></html>',
		content_type='text/html',
	)
	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/dialog')))

	await _drop_websocket_and_reconnect(browser_session)

	await _evaluate(browser_session, "setTimeout(() => { alert('after reconnect'); window.__dialogClosed = true; }, 0)")

	async def dialog_closed() -> bool:
		# Runtime.evaluate cannot run while alert() blocks the page, so this waits for dismissal.
		while True:
			if await _evaluate(browser_session, 'window.__dialogClosed ?? null'):
				return True
			await asyncio.sleep(0.05)

	try:
		closed = await asyncio.wait_for(dialog_closed(), timeout=5)
	except TimeoutError:
		closed = False
	assert closed, 'alert() was never dismissed after reconnect'


async def test_alert_opened_during_the_drop_does_not_hold_up_reconnect(
	browser_session: BrowserSession, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch
):
	"""A tab whose alert() opened while no CDP client was connected never replies to Page.enable or
	Network.enable, and the new client never sees that dialog. The reconnect handlers must skip it
	without holding up the event bus, and still set up the other pages."""
	httpserver.expect_request('/dialog').respond_with_data(
		'<html><head><title>Dialog</title></head><body><h1>Dialog page</h1></body></html>',
		content_type='text/html',
	)
	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/dialog')))
	tab = browser_session.agent_focus_target_id
	assert tab

	finished = await _drop_websocket_with_alert_open(browser_session, httpserver, monkeypatch, tab)
	assert finished, 'BrowserReconnectedEvent handlers waited on the tab whose alert() opened during the drop'

	# reconnect() moves focus to another page (here the about:blank it opens). The reconnect
	# handlers must set that page up too, after skipping the blocked tab.
	focused_tab = browser_session.agent_focus_target_id
	assert focused_tab and focused_tab != tab, 'reconnect() kept focus on the blocked tab'
	await _evaluate(
		browser_session,
		"setTimeout(() => { alert('after reconnect'); window.__dialogClosed = true; }, 0)",
		target_id=focused_tab,
	)

	async def dialog_closed() -> bool:
		# Runtime.evaluate cannot run while alert() blocks the page, so this waits for dismissal.
		while True:
			if await _evaluate(browser_session, 'window.__dialogClosed ?? null', target_id=focused_tab):
				return True
			await asyncio.sleep(0.05)

	try:
		closed = await asyncio.wait_for(dialog_closed(), timeout=5)
	except TimeoutError:
		closed = False
	assert closed, 'alert() in the focused tab was never dismissed after reconnect'


async def test_download_is_reported_after_reconnect(browser_session: BrowserSession, httpserver: HTTPServer):
	"""DownloadsWatchdog re-enables download events on the client created by reconnect()."""
	httpserver.expect_request('/report.csv').respond_with_data(
		'id,name\n1,alpha\n',
		content_type='text/csv',
		headers={'Content-Disposition': 'attachment; filename="report.csv"'},
	)
	httpserver.expect_request('/downloads').respond_with_data(
		f'<html><head><title>Downloads</title></head><body><a id="dl" href="{httpserver.url_for("/report.csv")}">report</a></body></html>',
		content_type='text/html',
	)
	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/downloads')))

	await _drop_websocket_and_reconnect(browser_session)

	downloaded = asyncio.ensure_future(browser_session.event_bus.expect(FileDownloadedEvent, timeout=10))
	await _evaluate(browser_session, "document.getElementById('dl').click()")
	try:
		event = await downloaded
	except TimeoutError:
		event = None

	assert isinstance(event, FileDownloadedEvent), 'no FileDownloadedEvent for a download after reconnect'
	assert event.file_name == 'report.csv'


async def test_captcha_events_are_handled_after_reconnect(browser_session: BrowserSession):
	"""CaptchaWatchdog registers its BrowserUse.* handlers on the client created by reconnect()."""
	await _drop_websocket_and_reconnect(browser_session)

	# BrowserUse.* events come from Browser Use cloud browsers; cdp-use's emit_event
	# delivers one through the new client's handler registry the same way.
	started = asyncio.ensure_future(browser_session.event_bus.expect(CaptchaSolverStartedEvent, timeout=5))
	handled = await browser_session.cdp_client.emit_event(
		'BrowserUse.captchaSolverStarted',
		{'targetId': 'target-1', 'vendor': 'recaptcha', 'url': 'http://localhost/captcha', 'startedAt': 0},
	)
	try:
		event = await started
	except TimeoutError:
		event = None

	assert handled, 'no BrowserUse.captchaSolverStarted handler on the reconnected CDP client'
	assert isinstance(event, CaptchaSolverStartedEvent)
	assert event.vendor == 'recaptcha'
