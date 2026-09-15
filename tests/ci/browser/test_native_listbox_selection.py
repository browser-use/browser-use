"""Real-browser coverage for listboxes whose onclick commits a dependent field."""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from browser_use.tools.frames import get_frame_evaluation_context, list_current_page_frames
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.tools.service import Tools


@pytest.fixture(scope='module')
def listbox_server() -> Iterator[HTTPServer]:
	server = HTTPServer(threaded=True)
	server.start()
	options = '<option value="v0" selected>Choice 0</option>' + ''.join(
		f'<option value="v{i}">Choice {i}</option>' for i in range(1, 250)
	)
	page = f"""<!doctype html><html><head><title>Lookup form</title></head><body>
		<div style="height:180px"></div>
		<input id="lookup-code" readonly onclick="picker.style.display='block'; picker.focus()">
		<select id="picker" size="8" style="display:none;width:220px"
			onclick="document.querySelector('#lookup-code').value=this.value; this.style.display='none'"
			onblur="this.style.display='none'">{options}</select>
		<output id="trace">[]</output>
		<script>
		const picker = document.querySelector('#picker');
		window.openerClicks = 0;
		document.querySelector('#lookup-code').addEventListener('click', () => window.openerClicks++);
		for (const type of ['input', 'change', 'click', 'blur']) {{
			picker.addEventListener(type, e => {{
				const trace = document.querySelector('#trace');
				trace.textContent = JSON.stringify([...JSON.parse(trace.textContent), {{type, trusted:e.isTrusted}}]);
			}});
		}}
		</script></body></html>"""
	server.expect_request('/form').respond_with_data(page, content_type='text/html')
	server.expect_request('/favicon.ico').respond_with_data('', status=204)
	for path, host in [('/frame', 'localhost'), ('/remote', '127.0.0.1')]:
		server.expect_request(path).respond_with_data(
			f"""<!doctype html><html><body style="margin:40px">
			<div style="height:900px"></div><iframe id="form-frame" src="http://{host}:{server.port}/form"
				style="border:5px solid;width:500px;height:360px"></iframe></body></html>""",
			content_type='text/html',
		)
	try:
		yield server
	finally:
		server.stop()


@pytest.fixture(scope='module')
async def listbox_browser() -> AsyncIterator[BrowserSession]:
	browser = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			use_cloud=False,
			enable_default_extensions=False,
			cross_origin_iframes=True,
			args=['--site-per-process'],
		)
	)
	await browser.start()
	try:
		yield browser
	finally:
		await browser.kill()
		await browser.event_bus.stop(clear=True, timeout=5)


async def _evaluate(browser: BrowserSession, expression: str, frame_id: str | None = None) -> Any:
	if frame_id:
		context = await get_frame_evaluation_context(browser, frame_id)
		session = context.session
		response = await session.cdp_client.send.Runtime.evaluate(
			params={'expression': expression, 'returnByValue': True, 'uniqueContextId': context.execution_context_unique_id},
			session_id=session.session_id,
		)
	else:
		session = await browser.get_or_create_cdp_session(focus=False)
		response = await session.cdp_client.send.Runtime.evaluate(
			params={'expression': expression, 'returnByValue': True}, session_id=session.session_id
		)
	assert not response.get('exceptionDetails'), response
	return response['result'].get('value')


async def _open(browser: BrowserSession, server: HTTPServer, path: str) -> tuple[int, str | None]:
	await browser.navigate_to(server.url_for(path))
	frame_id = None
	if path != '/form':
		async with asyncio.timeout(15):
			while True:
				frames = await list_current_page_frames(browser)
				matches = [frame for frame in frames.frames if frame.iframe_id == 'form-frame' and frame.title == 'Lookup form']
				if matches:
					frame_id = matches[0].frame_id
					break
				await asyncio.sleep(0.1)
	await _evaluate(
		browser, "document.querySelector('#lookup-code').click(); document.querySelector('#picker').scrollIntoView()", frame_id
	)
	state = await browser.get_browser_state_summary(include_screenshot=False)
	index = next(index for index, node in state.dom_state.selector_map.items() if node.attributes.get('id') == 'picker')
	return index, frame_id


async def _select(browser: BrowserSession, index: int, text: str) -> ActionResult:
	result = await Tools().registry.execute_action('select_dropdown', {'index': index, 'text': text}, browser_session=browser)
	assert isinstance(result, ActionResult)
	return result


async def _index(browser: BrowserSession, element_id: str) -> int:
	state = await browser.get_browser_state_summary(include_screenshot=False)
	return next(index for index, node in state.dom_state.selector_map.items() if node.attributes.get('id') == element_id)


async def _options(browser: BrowserSession, index: int) -> ActionResult:
	result = await Tools().registry.execute_action('dropdown_options', {'index': index}, browser_session=browser)
	assert isinstance(result, ActionResult)
	return result


async def _read(browser: BrowserSession, frame_id: str | None = None) -> dict:
	return await _evaluate(
		browser,
		"""({code: document.querySelector('#lookup-code').value,
			value: document.querySelector('#picker')?.value,
			events: JSON.parse(document.querySelector('#trace').textContent)})""",
		frame_id,
	)


@pytest.mark.parametrize('path', ['/form', '/frame', '/remote'])
@pytest.mark.parametrize('choice', [1, 240])
async def test_real_click_commits_readonly_field_once(listbox_browser, listbox_server, path, choice):
	index, frame_id = await _open(listbox_browser, listbox_server, path)
	result = await _select(listbox_browser, index, f'Choice {choice}')
	assert result.error is None, result
	assert result.metadata and result.metadata['selection_verified'] is True
	assert result.metadata['picker_source'] == 'inline-opener'
	assert result.metadata['readonly_input_value'] == f'v{choice}'
	actual = await _read(listbox_browser, frame_id)
	assert actual['code'] == actual['value'] == f'v{choice}'
	assert [event['type'] for event in actual['events']] in [['input', 'change', 'click'], ['input', 'change', 'click', 'blur']]
	assert all(event['trusted'] for event in actual['events'])


@pytest.mark.parametrize(
	'mutation,text',
	[
		("document.querySelector('#picker').disabled = true", 'v1'),
		("document.querySelector('#picker').options[1].disabled = true", 'v1'),
		("document.querySelector('#picker').options[1].hidden = true", 'v1'),
		(
			"document.querySelector('#picker').options[1].outerHTML = '<optgroup disabled><option value=v1>Choice 1</option></optgroup>'",
			'v1',
		),
		("document.querySelector('#picker').style.display = 'none'", 'v1'),
		("document.querySelector('#picker').inert = true", 'v1'),
		("document.querySelector('#picker').options[2].value = 'v1'", 'v1'),
		("document.body.insertAdjacentHTML('beforeend', '<div style=\"position:fixed;inset:0;z-index:1000\"></div>')", 'v1'),
		('void 0', 'missing'),
	],
)
async def test_unavailable_option_does_not_click_or_commit(listbox_browser, listbox_server, mutation, text):
	index, _ = await _open(listbox_browser, listbox_server, '/form')
	await _evaluate(listbox_browser, mutation)
	result = await _select(listbox_browser, index, text)
	assert result.error, result
	assert result.metadata and result.metadata['click_dispatched'] is False
	actual = await _read(listbox_browser)
	assert actual['code'] == '' and actual['value'] == 'v0'
	assert not [event for event in actual['events'] if event['type'] != 'blur']


@pytest.mark.parametrize('path', ['/frame', '/remote'])
async def test_parent_overlay_blocks_iframe_click(listbox_browser, listbox_server, path):
	index, frame_id = await _open(listbox_browser, listbox_server, path)
	await _evaluate(
		listbox_browser,
		"document.body.insertAdjacentHTML('beforeend', '<div style=\"position:fixed;inset:0;z-index:1000\"></div>')",
	)
	result = await _select(listbox_browser, index, 'v240')
	assert result.error and result.metadata and result.metadata['click_dispatched'] is False
	assert (await _read(listbox_browser, frame_id))['code'] == ''


@pytest.mark.parametrize('mutation', ["this.value='v0'", 'this.remove()'])
async def test_changed_after_click_reports_unverified_without_retry(listbox_browser, listbox_server, mutation):
	index, _ = await _open(listbox_browser, listbox_server, '/form')
	await _evaluate(listbox_browser, f"document.querySelector('#picker').setAttribute('onclick', {json.dumps(mutation)})")
	result = await _select(listbox_browser, index, 'v1')
	assert result.error and 'before retrying' in result.error
	assert result.metadata and result.metadata['click_dispatched'] is True and result.metadata['selection_verified'] is False
	actual = await _read(listbox_browser)
	assert actual['events'].count({'type': 'click', 'trusted': True}) == 1


async def test_already_selected_option_still_commits_once(listbox_browser, listbox_server):
	index, _ = await _open(listbox_browser, listbox_server, '/form')
	result = await _select(listbox_browser, index, 'v0')
	assert result.error is None, result
	actual = await _read(listbox_browser)
	assert actual['code'] == 'v0'
	assert [event['type'] for event in actual['events']] in [['click'], ['click', 'blur']]
	assert all(event['trusted'] for event in actual['events'])


@pytest.mark.parametrize(
	'mutation', ["document.querySelector('#picker').size = 1", "document.querySelector('#picker').multiple = true"]
)
async def test_other_native_selects_keep_existing_change_behavior(listbox_browser, listbox_server, mutation):
	index, _ = await _open(listbox_browser, listbox_server, '/form')
	await _evaluate(listbox_browser, mutation)
	result = await _select(listbox_browser, index, 'v1')
	assert result.error is None, result
	assert result.metadata is None
	actual = await _read(listbox_browser)
	assert actual['value'] == 'v1' and actual['code'] == ''
	assert [event['type'] for event in actual['events']] in [['input', 'change'], ['input', 'change', 'blur']]


async def test_same_origin_frame_with_cross_origin_support_disabled(listbox_server):
	browser = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True, user_data_dir=None, use_cloud=False, enable_default_extensions=False, cross_origin_iframes=False
		)
	)
	await browser.start()
	try:
		index, frame_id = await _open(browser, listbox_server, '/frame')
		result = await _select(browser, index, 'v240')
		assert result.error is None, result
		assert (await _read(browser, frame_id))['code'] == 'v240'
	finally:
		await browser.kill()
		await browser.event_bus.stop(clear=True, timeout=5)


@pytest.mark.parametrize('path', ['/form', '/frame', '/remote'])
@pytest.mark.parametrize('target', ['lookup-code', 'picker'])
async def test_dropdown_discovery_identifies_readonly_picker_without_clicking(listbox_browser, listbox_server, path, target):
	_, frame_id = await _open(listbox_browser, listbox_server, path)
	index = await _index(listbox_browser, target)
	before = await _read(listbox_browser, frame_id)
	result = await _options(listbox_browser, index)
	assert result.error is None, result
	assert 'read-only input' in (result.extracted_content or '')
	assert 'click the option' in (result.extracted_content or '')
	assert 'Choice 240' in (result.extracted_content or '')
	assert await _read(listbox_browser, frame_id) == before
	assert (await _select(listbox_browser, index, 'v240')).error is None
	assert (await _read(listbox_browser, frame_id))['code'] == 'v240'


@pytest.mark.parametrize(
	'relation',
	['named-opener', 'element-id', 'query-selector', 'aria-controls', 'aria-owns'],
)
async def test_readonly_input_discovery_and_selection_open_and_commit_once(listbox_browser, listbox_server, relation):
	await listbox_browser.navigate_to(listbox_server.url_for('/form'))
	if relation == 'element-id':
		await _evaluate(
			listbox_browser,
			"""document.querySelector('#lookup-code').setAttribute('onclick',
				"document.getElementById('picker').style.display='block'; document.getElementById('picker').focus()");""",
		)
	elif relation == 'query-selector':
		await _evaluate(
			listbox_browser,
			"""document.querySelector('#lookup-code').setAttribute('onclick',
				"document.querySelector('#picker').style.display='block'; document.querySelector('#picker').focus()");""",
		)
	elif relation.startswith('aria-'):
		await _evaluate(
			listbox_browser,
			f"""(() => {{
				const input = document.querySelector('#lookup-code');
				input.setAttribute({json.dumps(relation)}, 'picker');
				input.removeAttribute('onclick');
				input.addEventListener('click', () => {{ picker.style.display='block'; picker.focus(); }});
			}})()""",
		)
	index = await _index(listbox_browser, 'lookup-code')
	discovery = await _options(listbox_browser, index)
	assert discovery.error is None and 'read-only input' in (discovery.extracted_content or '')
	assert await _evaluate(listbox_browser, 'window.openerClicks') == 0
	assert (await _read(listbox_browser))['events'] == []
	result = await _select(listbox_browser, index, 'v240')
	assert result.error is None, result
	assert result.metadata and result.metadata['opener_click_dispatched'] is True
	assert await _evaluate(listbox_browser, 'window.openerClicks') == 1
	actual = await _read(listbox_browser)
	assert actual['code'] == actual['value'] == 'v240'
	assert actual['events'].count({'type': 'click', 'trusted': True}) == 1


@pytest.mark.parametrize(
	'mutation',
	[
		"input.removeAttribute('onclick')",
		'input.readOnly = false',
		"""input.setAttribute('onclick', "console.log('picker.style.display'); /* picker.focus() */")""",
	],
)
async def test_ordinary_listbox_keeps_value_selection_even_beside_an_input(listbox_browser, listbox_server, mutation):
	index, _ = await _open(listbox_browser, listbox_server, '/form')
	await _evaluate(listbox_browser, f"(() => {{ const input = document.querySelector('#lookup-code'); {mutation}; }})()")
	discovery = await _options(listbox_browser, index)
	assert discovery.error is None and 'read-only input' not in (discovery.extracted_content or '')
	result = await _select(listbox_browser, index, 'v1')
	assert result.error is None and result.metadata is None
	actual = await _read(listbox_browser)
	assert actual['value'] == 'v1' and actual['code'] == ''
	assert not any(event['type'] == 'click' for event in actual['events'])


async def test_select_rechecks_readonly_relationship_after_discovery(listbox_browser, listbox_server):
	index, _ = await _open(listbox_browser, listbox_server, '/form')
	assert 'read-only input' in ((await _options(listbox_browser, index)).extracted_content or '')
	await _evaluate(listbox_browser, "document.querySelector('#lookup-code').removeAttribute('onclick')")
	result = await _select(listbox_browser, index, 'v1')
	assert result.error is None and result.metadata is None
	assert (await _read(listbox_browser))['code'] == ''


async def test_plain_readonly_output_is_not_opened_or_written(listbox_browser, listbox_server):
	await listbox_browser.navigate_to(listbox_server.url_for('/form'))
	await _evaluate(listbox_browser, "document.querySelector('#lookup-code').removeAttribute('onclick')")
	index = await _index(listbox_browser, 'lookup-code')
	with pytest.raises(Exception, match='not recognizable dropdown'):
		await _options(listbox_browser, index)
	result = await _select(listbox_browser, index, 'v1')
	assert result.error and 'do not contain a dropdown' in result.error
	assert await _evaluate(listbox_browser, 'window.openerClicks') == 0
	assert (await _read(listbox_browser))['code'] == ''


@pytest.mark.parametrize('ambiguity', ['two-inputs', 'duplicate-listbox-id'])
async def test_ambiguous_readonly_picker_never_clicks_or_sets_value(listbox_browser, listbox_server, ambiguity):
	index, _ = await _open(listbox_browser, listbox_server, '/form')
	markup = '<input readonly aria-controls="picker">' if ambiguity == 'two-inputs' else '<select id="picker" size="4"></select>'
	await _evaluate(listbox_browser, f"document.body.insertAdjacentHTML('beforeend', {json.dumps(markup)})")
	result = await _select(listbox_browser, index, 'v1')
	assert result.error and 'unambiguous picker' in result.error
	assert result.metadata and result.metadata['click_dispatched'] is False
	assert (await _read(listbox_browser))['value'] == 'v0'
	assert (await _read(listbox_browser))['code'] == ''


async def test_regular_text_input_still_types_without_opening_picker(listbox_browser, listbox_server):
	await listbox_browser.navigate_to(listbox_server.url_for('/form'))
	await _evaluate(listbox_browser, "document.body.insertAdjacentHTML('beforeend', '<input id=free-text>')")
	index = await _index(listbox_browser, 'free-text')
	result = await Tools().registry.execute_action(
		'input', {'index': index, 'text': 'typed value'}, browser_session=listbox_browser
	)
	assert isinstance(result, ActionResult) and result.error is None
	assert await _evaluate(listbox_browser, "document.querySelector('#free-text').value") == 'typed value'
	assert await _evaluate(listbox_browser, 'window.openerClicks') == 0


async def test_picker_that_does_not_open_is_not_clicked_repeatedly(listbox_browser, listbox_server):
	await listbox_browser.navigate_to(listbox_server.url_for('/form'))
	await _evaluate(
		listbox_browser,
		"document.querySelector('#lookup-code').setAttribute('aria-controls', 'picker'); "
		"document.querySelector('#lookup-code').removeAttribute('onclick')",
	)
	index = await _index(listbox_browser, 'lookup-code')
	result = await _select(listbox_browser, index, 'v1')
	assert result.error and 'did not open' in result.error
	assert result.metadata and result.metadata['opener_click_dispatched'] is True and result.metadata['click_dispatched'] is False
	assert await _evaluate(listbox_browser, 'window.openerClicks') == 1
	assert (await _read(listbox_browser))['code'] == ''
