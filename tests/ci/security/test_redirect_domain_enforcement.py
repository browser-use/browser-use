"""allowed_domains must hold for every way a tab can reach a new origin, and before the request is sent.

'localhost' and '127.0.0.1' are different hosts pointing at the same test server, so allowing only
127.0.0.1 makes localhost the disallowed origin. The server logs every request it receives, which lets
each test assert that the disallowed page was never even requested.
"""

import asyncio
from collections.abc import Callable

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import BrowserErrorEvent, NavigateToUrlEvent

SECRET_HTML = '<html><body>secret</body></html>'


@pytest.fixture(scope='function')
def blocked_events() -> list[BrowserErrorEvent]:
	"""NavigationBlocked errors raised during the test, in order."""
	return []


@pytest.fixture(scope='function')
async def restricted_session(httpserver: HTTPServer, blocked_events: list[BrowserErrorEvent]):
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			allowed_domains=['127.0.0.1'],
		)
	)

	async def record_blocked(event: BrowserErrorEvent) -> None:
		if event.error_type == 'NavigationBlocked':
			blocked_events.append(event)

	session.event_bus.on(BrowserErrorEvent, record_blocked)
	await session.start()
	yield session
	await session.kill()


def _requests_to(httpserver: HTTPServer, path: str) -> int:
	return sum(1 for request, _ in httpserver.log if request.path == path)


def _secret_requests(httpserver: HTTPServer) -> int:
	return _requests_to(httpserver, '/secret')


async def _navigate(session: BrowserSession, url: str) -> None:
	event = session.event_bus.dispatch(NavigateToUrlEvent(url=url))
	await event
	await event.event_result(raise_if_any=False, raise_if_none=False)


async def _wait_until(condition: Callable[[], bool], what: str, timeout: float = 15.0) -> None:
	"""Poll until the condition holds, failing with a clear message at the deadline (no fixed sleeps)."""
	deadline = asyncio.get_event_loop().time() + timeout
	while not condition():
		assert asyncio.get_event_loop().time() < deadline, f'timed out waiting for: {what}'
		await asyncio.sleep(0.1)


def _page_urls(session: BrowserSession) -> list[str]:
	return [t.url for t in session.session_manager.get_all_page_targets()]


async def _assert_blocked(
	session: BrowserSession, httpserver: HTTPServer, blocked_events: list[BrowserErrorEvent], *, expect_unrequested: bool = True
) -> None:
	"""The policy must have actually fired for the disallowed URL, and left no tab on it."""
	blocked_prefix = f'http://localhost:{httpserver.port}'
	await _wait_until(
		lambda: any(blocked_prefix in str(e.details.get('url')) for e in blocked_events), 'a NavigationBlocked event'
	)
	await _wait_until(
		lambda: not any(u.startswith(blocked_prefix) for u in _page_urls(session)), 'no tab left on the disallowed origin'
	)
	if expect_unrequested:
		assert _secret_requests(httpserver) == 0, 'disallowed page reached the server'


async def test_redirect_to_disallowed_domain_is_blocked(restricted_session, httpserver: HTTPServer, blocked_events):
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/start').respond_with_data('', status=302, headers={'Location': blocked_url})
	httpserver.expect_request('/secret').respond_with_data(SECRET_HTML, content_type='text/html')

	await _navigate(restricted_session, f'http://127.0.0.1:{httpserver.port}/start')

	assert _requests_to(httpserver, '/start') >= 1, 'the allowed page was never requested, test is vacuous'
	await _assert_blocked(restricted_session, httpserver, blocked_events)


async def test_page_initiated_navigation_to_disallowed_domain_is_blocked(
	restricted_session, httpserver: HTTPServer, blocked_events
):
	"""location.href from a visited page is not an agent navigation but must still obey allowed_domains."""
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/start').respond_with_data(
		f'<html><body><script>setTimeout(() => location.href = "{blocked_url}", 300)</script></body></html>',
		content_type='text/html',
	)
	httpserver.expect_request('/secret').respond_with_data(SECRET_HTML, content_type='text/html')

	await _navigate(restricted_session, f'http://127.0.0.1:{httpserver.port}/start')

	assert _requests_to(httpserver, '/start') >= 1, 'the allowed page was never requested, test is vacuous'
	await _assert_blocked(restricted_session, httpserver, blocked_events)


async def test_window_open_to_disallowed_domain_is_blocked(restricted_session, httpserver: HTTPServer, blocked_events):
	"""A real window.open() call (with a user gesture) from an allowed page."""
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/start').respond_with_data('<html><body>start</body></html>', content_type='text/html')
	httpserver.expect_request('/secret').respond_with_data(SECRET_HTML, content_type='text/html')

	await _navigate(restricted_session, f'http://127.0.0.1:{httpserver.port}/start')
	assert _requests_to(httpserver, '/start') >= 1, 'the allowed page was never requested, test is vacuous'

	cdp_session = await restricted_session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': f'window.open("{blocked_url}"); 1', 'userGesture': True},
		session_id=cdp_session.session_id,
	)

	await _wait_until(lambda: len(_page_urls(restricted_session)) > 1, 'window.open to create a tab')
	await _assert_blocked(restricted_session, httpserver, blocked_events)


async def test_tab_created_on_disallowed_domain_is_blocked(restricted_session, httpserver: HTTPServer, blocked_events):
	"""A tab created out-of-band through CDP with a URL already set.

	Chrome starts that first request before browser-use can attach and intercept it, so this path is
	only blocked after the fact (the tab is sent to about:blank); it is not asserted to be unrequested.
	Tabs opened by pages (window.open) and the agent's own tabs are intercepted before any request.
	"""
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/secret').respond_with_data(SECRET_HTML, content_type='text/html')

	assert restricted_session._cdp_client_root is not None
	await restricted_session._cdp_client_root.send.Target.createTarget(params={'url': blocked_url})

	await _assert_blocked(restricted_session, httpserver, blocked_events, expect_unrequested=False)


async def test_iframe_on_disallowed_domain_is_not_loaded(restricted_session, httpserver: HTTPServer, blocked_events):
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/start').respond_with_data(
		f'<html><body>outer<iframe src="{blocked_url}"></iframe></body></html>', content_type='text/html'
	)
	httpserver.expect_request('/secret').respond_with_data(SECRET_HTML, content_type='text/html')

	await _navigate(restricted_session, f'http://127.0.0.1:{httpserver.port}/start')

	assert _requests_to(httpserver, '/start') >= 1, 'the allowed page was never requested, test is vacuous'
	await _assert_blocked(restricted_session, httpserver, blocked_events)


async def test_allowed_navigation_still_works(restricted_session, httpserver: HTTPServer, blocked_events):
	"""Interception must not get in the way of allowed pages, including allowed redirects."""
	httpserver.expect_request('/hop').respond_with_data('', status=302, headers={'Location': '/ok'})
	httpserver.expect_request('/ok').respond_with_data('<html><body>ok</body></html>', content_type='text/html')

	await _navigate(restricted_session, f'http://127.0.0.1:{httpserver.port}/hop')

	url = await restricted_session.get_current_page_url()
	assert url == f'http://127.0.0.1:{httpserver.port}/ok'
	assert blocked_events == []
