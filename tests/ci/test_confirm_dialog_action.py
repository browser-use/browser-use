"""JavaScript confirm() dialogs follow BrowserProfile.confirm_dialog_action ('accept' by default, or 'dismiss')."""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import NavigateToUrlEvent

CONFIRM_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Confirm</title></head>
<body>
	<p id="answer">none</p>
	<script>
		function ask() {
			document.getElementById('answer').textContent = confirm('Delete this item?') ? 'accepted' : 'dismissed';
		}
	</script>
</body>
</html>
"""


@pytest.fixture(scope='module')
def http_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/confirm').respond_with_data(CONFIRM_PAGE, content_type='text/html')
	yield server
	server.stop()


async def _answer_to_confirm(session: BrowserSession, url: str) -> str:
	"""Open the page, let it call confirm(), and return what confirm() returned."""
	await session.event_bus.dispatch(NavigateToUrlEvent(url=url))
	cdp_session = await session.get_or_create_cdp_session(focus=False)
	# Run confirm() outside this evaluate call, so the call does not wait on the dialog.
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': 'setTimeout(ask, 0)'},
		session_id=cdp_session.session_id,
	)
	answer = 'none'
	for _ in range(50):
		await asyncio.sleep(0.1)
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('answer').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		answer = result.get('result', {}).get('value')
		if answer != 'none':
			break
	return str(answer)


async def _start_session(**profile_kwargs) -> BrowserSession:
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True, **profile_kwargs))
	await session.start()
	return session


def test_default_is_accept():
	assert BrowserProfile().confirm_dialog_action == 'accept'


async def test_confirm_accepted_by_default(http_server):
	session = await _start_session()
	try:
		answer = await _answer_to_confirm(session, http_server.url_for('/confirm'))
		assert answer == 'accepted'
		assert '[confirm] Delete this item?' in session._closed_popup_messages
	finally:
		await session.kill()


async def test_confirm_dismissed_when_configured(http_server):
	session = await _start_session(confirm_dialog_action='dismiss')
	try:
		answer = await _answer_to_confirm(session, http_server.url_for('/confirm'))
		assert answer == 'dismissed'
		# The agent is told the dialog was answered with Cancel.
		assert '[confirm] Delete this item? (answered with Cancel)' in session._closed_popup_messages
	finally:
		await session.kill()


async def test_option_passes_through_browser_session_kwargs():
	session = BrowserSession(headless=True, confirm_dialog_action='dismiss')
	assert session.browser_profile.confirm_dialog_action == 'dismiss'
