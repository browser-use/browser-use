"""A redirect after an allowed navigation must be checked against the URL the tab landed on."""

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
