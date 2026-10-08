"""
Test that watchdogs keep working after the CDP WebSocket drops and auto-reconnects.

reconnect() replaces the CDP client, and cdp-use event handlers live on the client, so
every watchdog that registered CDP handlers has to register them again on the new one.

Usage:
	uv run pytest -vxs tests/ci/browser/test_reconnect_watchdogs.py
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

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


async def _evaluate(browser_session: BrowserSession, expression: str):
	cdp_session = await browser_session.get_or_create_cdp_session()
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': expression, 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	return result.get('result', {}).get('value')


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
