"""Clicking a disabled control must not report success.

Disabled form controls that have a click listener are still offered to the agent (the listener makes them look
interactive), but the browser never dispatches the click to them. The click action has to say so instead of
reporting "Clicked ...". The disabled state is read live, so a control enabled after the DOM snapshot (for example
by typing into a required field in the same step) is still clicked normally. aria-disabled elements do receive
clicks, so they are clicked as before.
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.events import ClickCoordinateEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools
from tests.ci.conftest import create_mock_llm

LISTENER = "<script>document.getElementById('target').addEventListener('click', () => { window.clicked = true })</script>"

PAGES = {
	'/disabled': '<button id="target" disabled>Place order</button>' + LISTENER,
	'/aria-disabled': '<div id="target" role="button" tabindex="0" aria-disabled="true">Place order</div>' + LISTENER,
	'/fieldset': '<fieldset disabled><button id="target" type="button">Place order</button></fieldset>' + LISTENER,
	'/disabled-print': '<button id="target" disabled onclick="window.print()">Print</button>' + LISTENER,
	'/enabled': '<button id="target">Place order</button>' + LISTENER,
	'/multi-act': '<input id="name"><button id="target" disabled>Place order</button><input id="note">' + LISTENER,
	'/enabled-later': (
		'<input id="name"><button id="target" disabled>Place order</button>'
		+ LISTENER
		+ "<script>document.getElementById('name').addEventListener('input', e => {"
		"document.getElementById('target').disabled = !e.target.value })</script>"
	),
}


@pytest.fixture(scope='module')
def http_server():
	server = HTTPServer()
	server.start()
	for path, body in PAGES.items():
		server.expect_request(path).respond_with_data(f'<html><body>{body}</body></html>', content_type='text/html')
	yield server
	server.stop()


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	yield session
	await session.kill()


async def _open(session: BrowserSession, tools: Tools, url: str) -> dict[str | None, int]:
	await tools.navigate(url=url, new_tab=False, browser_session=session)
	await asyncio.sleep(0.3)
	await session.get_browser_state_summary()
	return {(el.attributes or {}).get('id'): idx for idx, el in (await session.get_selector_map()).items()}


async def _clicked(session: BrowserSession) -> bool:
	cdp_session = await session.get_or_create_cdp_session()
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': 'window.clicked === true', 'returnByValue': True}, session_id=cdp_session.session_id
	)
	return result.get('result', {}).get('value') is True


@pytest.mark.parametrize('path', ['/disabled', '/fieldset', '/disabled-print'])
async def test_click_on_disabled_control_reports_error(browser_session, http_server, path):
	tools = Tools()
	indexes = await _open(browser_session, tools, http_server.url_for(path))
	assert 'target' in indexes, 'a disabled control with a click listener is offered to the agent'

	result = await tools.click(index=indexes['target'], browser_session=browser_session)

	assert result.error is not None and 'disabled' in result.error
	assert not await _clicked(browser_session)


@pytest.mark.parametrize('path', ['/enabled', '/aria-disabled'])
async def test_click_on_clickable_control_succeeds(browser_session, http_server, path):
	"""aria-disabled does not stop the browser from delivering the click, so it is not blocked."""
	tools = Tools()
	indexes = await _open(browser_session, tools, http_server.url_for(path))

	result = await tools.click(index=indexes['target'], browser_session=browser_session)

	assert result.error is None
	assert await _clicked(browser_session)


async def test_control_enabled_after_snapshot_is_clicked(browser_session, http_server):
	"""Uses the live state, not the snapshot: typing into the field enables the button before the click."""
	tools = Tools()
	indexes = await _open(browser_session, tools, http_server.url_for('/enabled-later'))
	await tools.input(index=indexes['name'], text='Ada', browser_session=browser_session)

	result = await tools.click(index=indexes['target'], browser_session=browser_session)

	assert result.error is None
	assert await _clicked(browser_session)


async def _center(session: BrowserSession, element_id: str) -> tuple[int, int]:
	cdp_session = await session.get_or_create_cdp_session()
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': f"(() => {{ const r = document.getElementById('{element_id}').getBoundingClientRect();"
			' return [Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2)]; })()',
			'returnByValue': True,
		},
		session_id=cdp_session.session_id,
	)
	value = result.get('result', {}).get('value')
	if not value or len(value) < 2:
		raise AssertionError(f'Could not read center of #{element_id}: {result.get("exceptionDetails")}')
	return int(value[0]), int(value[1])


@pytest.mark.parametrize(('path', 'clickable'), [('/disabled', False), ('/enabled', True)])
async def test_coordinate_click_on_disabled_control(browser_session, http_server, path, clickable):
	"""The coordinate path runs the same check among its safety checks (skipped when force=True, like the others)."""
	tools = Tools()
	await _open(browser_session, tools, http_server.url_for(path))
	x, y = await _center(browser_session, 'target')

	event = browser_session.event_bus.dispatch(ClickCoordinateEvent(coordinate_x=x, coordinate_y=y, force=False))
	await event
	click_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)

	is_error = isinstance(click_metadata, dict) and 'disabled' in click_metadata.get('validation_error', '')
	assert is_error is not clickable
	assert await _clicked(browser_session) is clickable


async def test_click_on_disabled_control_stops_multi_act(browser_session, http_server):
	"""Typing then clicking in one step: the click on the still-disabled button must stop the queued actions."""
	tools = Tools()
	indexes = await _open(browser_session, tools, http_server.url_for('/multi-act'))
	ActionModel = tools.registry.create_action_model()
	actions = [
		ActionModel.model_validate({'input': {'index': indexes['name'], 'text': 'Ada'}}),
		ActionModel.model_validate({'click': {'index': indexes['target']}}),
		ActionModel.model_validate({'input': {'index': indexes['note'], 'text': 'should not be typed'}}),
	]
	agent = Agent(task='test', llm=create_mock_llm(), browser_session=browser_session, tools=tools)

	results = await agent.multi_act(actions)

	assert len(results) == 2
	assert results[-1].error is not None and 'disabled' in results[-1].error
	cdp_session = await browser_session.get_or_create_cdp_session()
	note = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.getElementById('note').value", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	assert note.get('result', {}).get('value') == ''
	assert not await _clicked(browser_session)
