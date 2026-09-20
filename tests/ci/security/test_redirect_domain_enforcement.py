"""A redirect after an allowed navigation must be checked against the URL the tab landed on."""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import NavigateToUrlEvent


@pytest.fixture(scope='function')
async def restricted_session(httpserver: HTTPServer):
	# only the 127.0.0.1 host is allowed; 'localhost' is a different host pointing at the same server
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


async def test_redirect_to_disallowed_domain_is_blocked(restricted_session, httpserver: HTTPServer):
	allowed_url = f'http://127.0.0.1:{httpserver.port}'
	blocked_url = f'http://localhost:{httpserver.port}/secret'

	httpserver.expect_request('/start').respond_with_data('', status=302, headers={'Location': blocked_url})
	httpserver.expect_request('/secret').respond_with_data('<html><body>secret</body></html>', content_type='text/html')

	event = restricted_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{allowed_url}/start'))
	await event
	await event.event_result(raise_if_any=False, raise_if_none=False)

	# the tab must not be left on the redirect target
	current_url = await restricted_session.get_current_page_url()
	assert 'localhost' not in current_url, f'redirect to disallowed domain was not blocked: {current_url}'


async def _wait_for_target_url(session, predicate, timeout: float = 15.0):
	"""Poll the page targets until one satisfies the predicate; return the matching URLs."""
	deadline = asyncio.get_event_loop().time() + timeout
	while True:
		urls = [t.url for t in session.session_manager.get_all_page_targets()]
		if predicate(urls) or asyncio.get_event_loop().time() > deadline:
			return urls
		await asyncio.sleep(0.25)


async def test_page_initiated_navigation_to_disallowed_domain_is_blocked(restricted_session, httpserver: HTTPServer):
	"""location.href from a visited page is not an agent navigation but must still obey allowed_domains."""
	allowed_url = f'http://127.0.0.1:{httpserver.port}'
	blocked_url = f'http://localhost:{httpserver.port}/secret'

	httpserver.expect_request('/start').respond_with_data(
		f'<html><body><script>setTimeout(() => location.href = "{blocked_url}", 300)</script></body></html>',
		content_type='text/html',
	)
	httpserver.expect_request('/secret').respond_with_data('<html><body>secret</body></html>', content_type='text/html')

	event = restricted_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{allowed_url}/start'))
	await event
	await event.event_result(raise_if_any=False, raise_if_none=False)

	urls = await _wait_for_target_url(
		restricted_session, lambda urls: not any('localhost' in u for u in urls) and any('about:blank' in u for u in urls)
	)
	assert not any('localhost' in u for u in urls), f'page-initiated navigation was not blocked: {urls}'


async def test_tab_opened_on_disallowed_domain_is_blocked(restricted_session, httpserver: HTTPServer):
	"""A tab created by the page (window.open / target=_blank) never goes through NavigateToUrlEvent."""
	blocked_url = f'http://localhost:{httpserver.port}/secret'
	httpserver.expect_request('/secret').respond_with_data('<html><body>secret</body></html>', content_type='text/html')

	assert restricted_session._cdp_client_root is not None
	await restricted_session._cdp_client_root.send.Target.createTarget(params={'url': blocked_url})

	urls = await _wait_for_target_url(restricted_session, lambda urls: not any('localhost' in u for u in urls) and len(urls) > 1)
	assert not any('localhost' in u for u in urls), f'tab opened on disallowed domain was not blocked: {urls}'
