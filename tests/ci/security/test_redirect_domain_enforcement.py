"""allowed_domains must hold for every way a tab can reach a new origin, and before the request is sent.

'localhost' and '127.0.0.1' are different hosts pointing at the same test server, so allowing only
127.0.0.1 makes localhost the disallowed origin. The server logs every request it receives, which lets
each test assert that the disallowed page was never even requested.
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import NavigateToUrlEvent

SECRET_HTML = '<html><body>secret</body></html>'


@pytest.fixture(scope='function')
async def restricted_session(httpserver: HTTPServer):
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			allowed_domains=['127.0.0.1'],
		)
	)
	await session.start()
	yield session
	await session.kill()


def _secret_requests(httpserver: HTTPServer) -> int:
	return sum(1 for request, _ in httpserver.log if request.path == '/secret')


async def _navigate(session: BrowserSession, url: str) -> None:
	event = session.event_bus.dispatch(NavigateToUrlEvent(url=url))
	await event
	await event.event_result(raise_if_any=False, raise_if_none=False)


async def _settle(session: BrowserSession, seconds: float = 3.0) -> list[str]:
	"""Give the browser time to attempt any pending navigation, then return all page URLs."""
	await asyncio.sleep(seconds)
	return [t.url for t in session.session_manager.get_all_page_targets()]


async def test_redirect_to_disallowed_domain_is_blocked(restricted_session, httpserver: HTTPServer):
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/start').respond_with_data('', status=302, headers={'Location': blocked_url})
	httpserver.expect_request('/secret').respond_with_data(SECRET_HTML, content_type='text/html')

	await _navigate(restricted_session, f'http://127.0.0.1:{httpserver.port}/start')

	urls = await _settle(restricted_session)
	assert not any(u.startswith(f'http://localhost:{httpserver.port}') for u in urls), urls
	assert _secret_requests(httpserver) == 0, 'disallowed redirect target was requested'


async def test_page_initiated_navigation_to_disallowed_domain_is_blocked(restricted_session, httpserver: HTTPServer):
	"""location.href from a visited page is not an agent navigation but must still obey allowed_domains."""
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/start').respond_with_data(
		f'<html><body><script>setTimeout(() => location.href = "{blocked_url}", 300)</script></body></html>',
		content_type='text/html',
	)
	httpserver.expect_request('/secret').respond_with_data(SECRET_HTML, content_type='text/html')

	await _navigate(restricted_session, f'http://127.0.0.1:{httpserver.port}/start')

	urls = await _settle(restricted_session)
	assert not any(u.startswith(f'http://localhost:{httpserver.port}') for u in urls), urls
	assert _secret_requests(httpserver) == 0, 'page-initiated navigation reached the disallowed server'


async def test_window_open_to_disallowed_domain_is_blocked(restricted_session, httpserver: HTTPServer):
	"""A real window.open() call (with a user gesture) from an allowed page."""
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/start').respond_with_data('<html><body>start</body></html>', content_type='text/html')
	httpserver.expect_request('/secret').respond_with_data(SECRET_HTML, content_type='text/html')

	await _navigate(restricted_session, f'http://127.0.0.1:{httpserver.port}/start')

	cdp_session = await restricted_session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': f'window.open("{blocked_url}"); 1', 'userGesture': True},
		session_id=cdp_session.session_id,
	)

	urls = await _settle(restricted_session)
	assert len(urls) > 1, f'window.open did not create a tab, test is not exercising the popup path: {urls}'
	assert not any(u.startswith(f'http://localhost:{httpserver.port}') for u in urls), urls
	assert _secret_requests(httpserver) == 0, 'window.open target reached the disallowed server'


async def test_tab_created_on_disallowed_domain_is_blocked(restricted_session, httpserver: HTTPServer):
	"""A tab created out-of-band through CDP with a URL already set.

	Chrome starts that first request before browser-use can attach and intercept it, so this path is
	only blocked after the fact (the tab is sent to about:blank); it is not asserted to be unrequested.
	Tabs opened by pages (window.open) and the agent's own tabs are intercepted before any request.
	"""
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/secret').respond_with_data(SECRET_HTML, content_type='text/html')

	assert restricted_session._cdp_client_root is not None
	await restricted_session._cdp_client_root.send.Target.createTarget(params={'url': blocked_url})

	urls = await _settle(restricted_session)
	assert not any(u.startswith(f'http://localhost:{httpserver.port}') for u in urls), urls


async def test_iframe_on_disallowed_domain_is_not_loaded(restricted_session, httpserver: HTTPServer):
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/start').respond_with_data(
		f'<html><body>outer<iframe src="{blocked_url}"></iframe></body></html>', content_type='text/html'
	)
	httpserver.expect_request('/secret').respond_with_data(SECRET_HTML, content_type='text/html')

	await _navigate(restricted_session, f'http://127.0.0.1:{httpserver.port}/start')

	await _settle(restricted_session)
	assert _secret_requests(httpserver) == 0, 'iframe on a disallowed domain was requested'


async def test_allowed_navigation_still_works(restricted_session, httpserver: HTTPServer):
	"""Interception must not get in the way of allowed pages, including allowed redirects."""
	httpserver.expect_request('/hop').respond_with_data('', status=302, headers={'Location': '/ok'})
	httpserver.expect_request('/ok').respond_with_data('<html><body>ok</body></html>', content_type='text/html')

	await _navigate(restricted_session, f'http://127.0.0.1:{httpserver.port}/hop')

	url = await restricted_session.get_current_page_url()
	assert url == f'http://127.0.0.1:{httpserver.port}/ok'
