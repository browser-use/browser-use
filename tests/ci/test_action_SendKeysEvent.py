"""send_keys must type a key's text the way Chrome does for a real keypress.

A chat composer that sends on Enter and adds a line on Shift+Enter shows both faults:

- Shift+Enter: the combination path sent Enter's keyDown with the Shift modifier but no `text`.
  Chrome inserts a character only when the keyDown carries text, so the page saw shiftKey=true
  (and did not send) but no newline appeared.
- Enter: the plain path sent the text as a separate char event, which Chrome inserts even after
  the page prevented the keydown's default, so a composer that sends and clears itself was left
  holding a newline.
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import SendKeysEvent
from browser_use.tools.service import Tools

_MESSAGE = 'First line'

# The composer sends on Enter without Shift, like most chat inputs. The notes textarea has no
# handler, so it shows what the browser itself inserts.
_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Chat composer</title></head>
<body>
	<textarea id="composer" rows="2"></textarea>
	<form id="search"><input id="query" name="q"></form>
	<textarea id="notes" rows="2"></textarea>
	<script>
		window.keydowns = [];
		window.submitted = [];
		window.keypresses = [];
		window.searches = 0;
		window.noteKeydowns = [];
		const composer = document.getElementById('composer');
		composer.addEventListener('keydown', (e) => {
			window.keydowns.push({key: e.key, shift: e.shiftKey});
			if (e.key === 'Enter' && !e.shiftKey) {
				e.preventDefault();
				window.submitted.push(composer.value);
				composer.value = '';
			}
		});
		const query = document.getElementById('query');
		query.addEventListener('keypress', (e) => window.keypresses.push(e.key));
		document.getElementById('search').addEventListener('submit', (e) => {
			e.preventDefault();
			window.searches += 1;
		});
		const notes = document.getElementById('notes');
		notes.addEventListener('keydown', (e) =>
			window.noteKeydowns.push({key: e.key, ctrl: e.ctrlKey, alt: e.altKey, meta: e.metaKey})
		);
	</script>
</body>
</html>
"""

_FOCUS_COMPOSER = (
	f'composer.focus(); composer.value = {_MESSAGE!r}; composer.setSelectionRange(composer.value.length, composer.value.length);'
)
_FOCUS_NOTES = f'notes.focus(); notes.value = {_MESSAGE!r}; notes.setSelectionRange(notes.value.length, notes.value.length);'
_STATE = '({value: composer.value, submitted, keydowns, keypresses, searches, notes: notes.value, noteKeydowns})'


@pytest.fixture(scope='module')
def http_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/composer').respond_with_data(_PAGE, content_type='text/html')
	server.expect_request('/favicon.ico').respond_with_data(b'', content_type='image/x-icon')
	yield server
	server.stop()


@pytest.fixture(scope='module')
def composer_url(http_server):
	return f'http://{http_server.host}:{http_server.port}/composer'


async def _eval(session: BrowserSession, expression: str):
	cdp = await session.get_or_create_cdp_session()
	res = await asyncio.wait_for(
		cdp.cdp_client.send.Runtime.evaluate(
			params={'expression': expression, 'returnByValue': True},
			session_id=cdp.session_id,
		),
		timeout=10,
	)
	return res.get('result', {}).get('value')


async def _send_keys(composer_url: str, focus_js: str, keys: str) -> dict:
	"""Open the page, run `focus_js` to focus a field, send `keys` and return the page state."""
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await asyncio.wait_for(session.start(), timeout=60)
	try:
		await Tools().navigate(url=composer_url, new_tab=False, browser_session=session)
		await _eval(session, focus_js)
		event = session.event_bus.dispatch(SendKeysEvent(keys=keys))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)
		state = await _eval(session, _STATE)
		assert isinstance(state, dict)
		return state
	finally:
		await session.kill()


async def test_shift_enter_inserts_a_newline_without_sending(composer_url):
	state = await _send_keys(composer_url, _FOCUS_COMPOSER, 'Shift+Enter')
	assert state['keydowns'][-1] == {'key': 'Enter', 'shift': True}
	assert state['submitted'] == []
	assert state['value'] == f'{_MESSAGE}\n'


async def test_enter_sends_and_leaves_no_newline(composer_url):
	"""The composer prevents Enter's default and clears itself, so no newline may follow the send."""
	state = await _send_keys(composer_url, _FOCUS_COMPOSER, 'Enter')
	assert state['submitted'] == [_MESSAGE]
	assert state['value'] == ''


async def test_enter_fires_keypress_and_submits_a_form(composer_url):
	state = await _send_keys(composer_url, "query.value = 'docs'; query.focus();", 'Enter')
	assert state['keypresses'] == ['Enter']
	assert state['searches'] == 1


@pytest.mark.parametrize(('keys', 'modifier'), [('Control+Enter', 'ctrl'), ('Alt+Enter', 'alt'), ('Meta+Enter', 'meta')])
async def test_enter_with_control_alt_or_meta_types_no_text(composer_url, keys, modifier):
	"""Chrome drops Enter's text when Control, Alt or Meta is held, so the chord reaches the page and inserts nothing."""
	state = await _send_keys(composer_url, _FOCUS_NOTES, keys)
	assert state['noteKeydowns'][-1]['key'] == 'Enter'
	assert state['noteKeydowns'][-1][modifier] is True
	assert state['notes'] == _MESSAGE
