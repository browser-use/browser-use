"""Opening a new tab must not reuse an about:blank tab that a page wrote into.

A window opened with window.open('') and filled by its opener (document.write) keeps the URL
about:blank. Navigating with new_tab=True reuses about:blank tabs, which would throw that content
away. Only empty ones may be reused.
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import NavigateToUrlEvent, SwitchTabEvent

WRITTEN = '<title>Help</title><h1>Help text</h1>'


@pytest.fixture(scope='module')
def http_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/home').respond_with_data('<h1>Home</h1>', content_type='text/html')
	server.expect_request('/next').respond_with_data('<h1>Next</h1>', content_type='text/html')
	yield server
	server.stop()


@pytest.fixture
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	yield session
	await session.kill()


async def _open_blank_tab(session: BrowserSession, html: str | None) -> str:
	"""Open an about:blank tab in the background and, if html is given, write it in like an opener would."""
	assert session._cdp_client_root is not None
	created = await session._cdp_client_root.send.Target.createTarget(params={'url': 'about:blank', 'background': True})
	target_id = created['targetId']
	for _ in range(50):
		if any(target.target_id == target_id for target in session.session_manager.get_all_page_targets()):
			break
		await asyncio.sleep(0.1)
	if html is not None:
		cdp_session = await session.get_or_create_cdp_session(target_id=target_id, focus=False)
		await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': f'document.open(); document.write({html!r}); document.close(); 1'},
			session_id=cdp_session.session_id,
		)
	return target_id


async def _text_of(session: BrowserSession, target_id: str) -> str:
	cdp_session = await session.get_or_create_cdp_session(target_id=target_id, focus=False)
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': 'document.body ? document.body.innerText : ""', 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	return result['result'].get('value', '')


async def _add_loading_animation(session: BrowserSession, target_id: str) -> None:
	"""The element AboutBlankWatchdog's loading animation adds to a blank tab (without its remote image)."""
	cdp_session = await session.get_or_create_cdp_session(target_id=target_id, focus=False)
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': "const d = document.createElement('div'); d.id = 'pretty-loading-animation'; document.body.appendChild(d); 1",
		},
		session_id=cdp_session.session_id,
	)


async def _count_of(session: BrowserSession, target_id: str, selector: str) -> int:
	cdp_session = await session.get_or_create_cdp_session(target_id=target_id, focus=False)
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': f'document.querySelectorAll({selector!r}).length', 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	return result['result'].get('value', 0)


async def test_new_tab_does_not_reuse_a_written_blank_tab(browser_session, http_server):
	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=http_server.url_for('/home')))
	written = await _open_blank_tab(browser_session, WRITTEN)

	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=http_server.url_for('/next'), new_tab=True))

	assert browser_session.agent_focus_target_id != written
	assert 'Help text' in await _text_of(browser_session, written)


async def test_new_tab_from_a_written_blank_tab_opens_another_tab(browser_session, http_server):
	written = await _open_blank_tab(browser_session, WRITTEN)
	await browser_session.event_bus.dispatch(SwitchTabEvent(target_id=written))

	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=http_server.url_for('/next'), new_tab=True))

	assert browser_session.agent_focus_target_id != written
	assert 'Help text' in await _text_of(browser_session, written)


async def test_new_tab_does_not_reuse_a_blank_tab_written_without_text(browser_session, http_server):
	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=http_server.url_for('/home')))
	written = await _open_blank_tab(browser_session, '<form><input name="q"></form>')

	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=http_server.url_for('/next'), new_tab=True))

	assert browser_session.agent_focus_target_id != written
	assert await _count_of(browser_session, written, 'input') == 1


async def test_new_tab_still_reuses_an_empty_blank_tab(browser_session, http_server):
	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=http_server.url_for('/home')))
	empty = await _open_blank_tab(browser_session, None)
	# Blank tabs normally carry AboutBlankWatchdog's loading animation; that alone is not content.
	await _add_loading_animation(browser_session, empty)
	tabs_before = len(browser_session.session_manager.get_all_page_targets())

	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=http_server.url_for('/next'), new_tab=True))

	assert browser_session.agent_focus_target_id == empty
	assert len(browser_session.session_manager.get_all_page_targets()) == tabs_before
