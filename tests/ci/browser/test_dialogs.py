"""
Test that JavaScript dialogs are dismissed without stalling the CDP connection.

cdp-use awaits async event handlers inside its WebSocket read loop. A dialog handler
that awaits its Page.handleJavaScriptDialog reply from there blocks the very loop that
would deliver the reply, so every dismissal used to time out (0.5s per attempt) while
all other CDP traffic stalled.

Usage:
	uv run pytest -vxs tests/ci/browser/test_dialogs.py
"""

import asyncio
import logging

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import NavigateToUrlEvent


class _LogRecorder(logging.Handler):
	"""Collects browser_use log messages (that logger does not propagate to caplog)."""

	def __init__(self) -> None:
		super().__init__(level=logging.DEBUG)
		self.messages: list[str] = []

	def emit(self, record: logging.LogRecord) -> None:
		self.messages.append(record.getMessage())


@pytest.fixture
def log_messages():
	recorder = _LogRecorder()
	logger = logging.getLogger('browser_use')
	original_level = logger.level
	logger.addHandler(recorder)
	logger.setLevel(logging.DEBUG)
	yield recorder.messages
	logger.removeHandler(recorder)
	logger.setLevel(original_level)


@pytest.fixture
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await session.start()
	yield session
	await session.kill()


async def _wait_for_page_value(browser_session: BrowserSession, expression: str, timeout: float = 5.0):
	"""Poll a JS expression in the focused page until it returns something other than null."""
	cdp_session = await browser_session.get_or_create_cdp_session()
	loop = asyncio.get_event_loop()
	deadline = loop.time() + timeout
	while (remaining := deadline - loop.time()) > 0:
		# Bound each call too: a stalled CDP reply must not outlast the deadline.
		try:
			result = await asyncio.wait_for(
				cdp_session.cdp_client.send.Runtime.evaluate(
					params={'expression': expression, 'returnByValue': True},
					session_id=cdp_session.session_id,
				),
				timeout=remaining,
			)
		except TimeoutError:
			return None
		value = result.get('result', {}).get('value')
		if value is not None:
			return value
		await asyncio.sleep(0.05)
	return None


async def test_alert_is_dismissed_without_stalling_cdp(browser_session: BrowserSession, httpserver: HTTPServer, log_messages):
	"""alert() is dismissed by the first CDP attempt, with no handler timeouts."""
	httpserver.expect_request('/dialog').respond_with_data(
		'<html><head><title>Dialog</title></head><body><h1>Dialog page</h1></body></html>',
		content_type='text/html',
	)
	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/dialog')))

	cdp_session = await browser_session.get_or_create_cdp_session()
	loop = asyncio.get_event_loop()
	started = loop.time()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "setTimeout(() => { alert('hello from the test page'); window.__dialogClosed = true; }, 0)"},
		session_id=cdp_session.session_id,
	)

	# alert() blocks the page until the dialog is closed, and a stalled handler also holds
	# up the replies to these polls, so this measures how long CDP traffic was blocked.
	closed = await _wait_for_page_value(browser_session, 'window.__dialogClosed ?? null')
	elapsed = loop.time() - started

	assert closed, 'alert() was never dismissed'
	assert any('Dialog handled successfully' in message for message in log_messages), (
		'dialog handler never reported a successful dismissal'
	)
	timeouts = [message for message in log_messages if 'failed: TimeoutError' in message]
	assert not timeouts, f'dialog handler timed out waiting for CDP: {timeouts}'
	# Each timed-out attempt in the handler costs 500 ms; a stalled handler holds replies for ~2s.
	assert elapsed < 1.0, f'CDP replies were held up for {elapsed:.2f}s while the dialog was handled'
