"""A page written with document.write() into an about:blank tab keeps the URL about:blank.

This is what a window opened with window.open('') and filled by its opener looks like. It has
content, so it must be read like any other page, not reported as an empty tab.
"""

import pytest

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import NavigateToUrlEvent

WRITTEN_PAGE = '<title>Help</title><h1>Help text</h1><button id="got-it">Got it</button>'


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	yield session
	await session.kill()


async def _blank_tab(session: BrowserSession, html: str | None) -> None:
	"""Go to about:blank and, if html is given, write it into the page the way an opener would."""
	await session.event_bus.dispatch(NavigateToUrlEvent(url='about:blank'))
	if html is None:
		return
	cdp_session = await session.get_or_create_cdp_session(focus=False)
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': f'document.open(); document.write({html!r}); document.close(); 1'},
		session_id=cdp_session.session_id,
	)


async def test_written_about_blank_page_is_read(browser_session):
	await _blank_tab(browser_session, WRITTEN_PAGE)

	state = await browser_session.get_browser_state_summary(include_screenshot=False)

	assert state.url == 'about:blank'
	assert state.title != 'Empty Tab'
	page_text = state.dom_state.llm_representation()
	assert 'Help text' in page_text
	assert 'Got it' in page_text
	assert len(state.dom_state.selector_map) >= 1


async def test_written_about_blank_page_without_text_is_read(browser_session):
	await _blank_tab(browser_session, '<form><input name="q" placeholder="Search"></form>')

	state = await browser_session.get_browser_state_summary(include_screenshot=False)

	assert state.title != 'Empty Tab'
	assert len(state.dom_state.selector_map) >= 1


async def test_plain_about_blank_is_still_an_empty_tab(browser_session):
	await _blank_tab(browser_session, None)
	# Blank tabs normally carry AboutBlankWatchdog's loading animation; that alone is not content.
	# (Its element is added directly, without the animation's remote image.)
	cdp_session = await browser_session.get_or_create_cdp_session(focus=False)
	added = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			# Wait for the blank document's body, as the watchdog's own script does.
			'expression': "new Promise((resolve) => { const add = () => { const d = document.createElement('div'); "
			"d.id = 'pretty-loading-animation'; document.body.appendChild(d); "
			"resolve(document.querySelectorAll('#pretty-loading-animation').length); }; "
			"document.body ? add() : document.addEventListener('DOMContentLoaded', add); })",
			'awaitPromise': True,
			'returnByValue': True,
		},
		session_id=cdp_session.session_id,
	)
	assert added['result'].get('value') == 1

	state = await browser_session.get_browser_state_summary(include_screenshot=False)

	assert state.title == 'Empty Tab'
	assert state.dom_state.selector_map == {}
