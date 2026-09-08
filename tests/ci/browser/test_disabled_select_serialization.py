"""Expose live values of visible disabled selects without assigning action indices."""

import json
from collections.abc import AsyncIterator, Iterator

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.profile import ViewportSize
from browser_use.dom.views import SerializedDOMState
from browser_use.tools.service import Tools


@pytest.fixture(scope='module')
async def select_browser() -> AsyncIterator[BrowserSession]:
	"""Use a real browser without an LLM or optional browser extensions."""
	browser = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			use_cloud=False,
			enable_default_extensions=False,
			window_size=ViewportSize(width=1280, height=1000),
		)
	)
	await browser.start()
	try:
		yield browser
	finally:
		await browser.kill()
		await browser.event_bus.stop(clear=True, timeout=5)


@pytest.fixture
def select_server() -> Iterator[HTTPServer]:
	server = HTTPServer(host='127.0.0.1', threaded=True)
	server.start()
	server.expect_request('/favicon.ico').respond_with_data('', status=204)
	try:
		yield server
	finally:
		server.stop()


async def _open_form(browser: BrowserSession, server: HTTPServer, controls: str) -> None:
	server.expect_request('/form').respond_with_data(
		f'<!doctype html><html><head><meta charset="utf-8"><title>Form</title></head>'
		f'<body><h1>Form</h1><button id="save-form" type="button">Save form</button>{controls}</body></html>',
		content_type='text/html; charset=utf-8',
	)
	await browser.navigate_to(server.url_for('/form'))


async def _dom_state(browser: BrowserSession) -> SerializedDOMState:
	state = await browser.get_browser_state_summary(include_screenshot=False, include_recent_events=False, cached=False)
	assert any(node.attributes.get('id') == 'save-form' for node in state.dom_state.selector_map.values()), (
		f'The ordinary button must be captured before checking dropdown serialization: {state.dom_state.llm_representation()}'
	)
	assert 'Save form' in state.dom_state.llm_representation()
	return state.dom_state


def _reported_selection(state: SerializedDOMState) -> list[dict[str, str]]:
	serialized = state.llm_representation()
	select_lines = [line for line in serialized.splitlines() if '<select' in line]
	assert len(select_lines) == 1, f'The visible select should remain identifiable: {serialized}'
	select_line = select_lines[0]
	assert 'selected=' in select_line, f'The current selection must be explicit: {select_line}'
	selected, _ = json.JSONDecoder().raw_decode(select_line.split('selected=', 1)[1])
	assert isinstance(selected, list)
	return selected


def _assert_disabled_controls_not_indexed(state: SerializedDOMState) -> None:
	indexed_controls = [node for node in state.selector_map.values() if node.tag_name.lower() in {'select', 'option', 'optgroup'}]
	assert not indexed_controls, f'Disabled dropdowns and their options must not be actionable: {state.llm_representation()}'
	select_line = next(line for line in state.llm_representation().splitlines() if '<select' in line)
	assert 'disabled' in select_line


async def test_disabled_select_reports_implicit_first_option(select_browser: BrowserSession, select_server: HTTPServer):
	"""The browser selects the first option even when HTML has no selected attribute."""
	await _open_form(
		select_browser,
		select_server,
		'<select id="status" name="status" disabled><option value="active">Active</option></select>',
	)
	session = await select_browser.get_or_create_cdp_session()
	readback = await session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': "({value: document.querySelector('select').value, selectedAttribute: document.querySelector('option').hasAttribute('selected')})",
			'returnByValue': True,
		},
		session_id=session.session_id,
	)
	assert readback['result'].get('value') == {'value': 'active', 'selectedAttribute': False}
	state = await _dom_state(select_browser)
	assert _reported_selection(state) == [{'value': 'active', 'label': 'Active'}]
	_assert_disabled_controls_not_indexed(state)


@pytest.mark.parametrize(
	('selected_index', 'expected_selection'),
	[
		pytest.param(1, [{'value': 'active', 'label': 'Active'}], id='selection-changed'),
		pytest.param(-1, [], id='selection-cleared'),
	],
)
async def test_disabled_select_reports_live_selection_after_script_change(
	select_browser: BrowserSession,
	select_server: HTTPServer,
	selected_index: int,
	expected_selection: list[dict[str, str]],
):
	"""HTML defaults remain unchanged when the live selection changes or is cleared."""
	await _open_form(
		select_browser,
		select_server,
		'<select id="status" name="status" disabled>'
		'<option value="draft" selected>Draft</option>'
		'<option value="active">Active</option></select>',
	)
	initial_state = await _dom_state(select_browser)
	assert _reported_selection(initial_state) == [{'value': 'draft', 'label': 'Draft'}]
	session = await select_browser.get_or_create_cdp_session()
	mutation = await session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': f"document.querySelector('select').selectedIndex = {selected_index}",
			'returnByValue': True,
		},
		session_id=session.session_id,
	)
	assert not mutation.get('exceptionDetails'), mutation
	readback = await session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': """(() => {
				const select = document.querySelector('select');
				return {
					selected: Array.from(select.selectedOptions, option => ({value: option.value, label: option.label})),
					selectedAttributes: Array.from(select.options, option => option.hasAttribute('selected'))
				};
			})()""",
			'returnByValue': True,
		},
		session_id=session.session_id,
	)
	assert readback['result'].get('value') == {'selected': expected_selection, 'selectedAttributes': [True, False]}
	updated_state = await _dom_state(select_browser)
	assert _reported_selection(updated_state) == expected_selection
	_assert_disabled_controls_not_indexed(updated_state)


@pytest.mark.parametrize(
	('options', 'expected_selection'),
	[
		pytest.param(
			'<optgroup label="Available">'
			'<option value="active" label="Active" selected>internal-active</option>'
			'<option value="pending" label="Pending">internal-pending</option>'
			'</optgroup><optgroup label="Completed">'
			'<option value="archived" label="Archived" selected>internal-archived</option></optgroup>',
			[{'value': 'active', 'label': 'Active'}, {'value': 'archived', 'label': 'Archived'}],
			id='selected-labels-in-optgroups',
		),
		pytest.param(
			'<option value="" label="Choose status" selected>internal-placeholder</option>'
			'<option label="" selected>Text fallback</option>'
			'<option value="empty-label" label="" selected>Empty label fallback</option>'
			'<option value="missing-label" selected>Missing label fallback</option>'
			'<option value="" label="" selected></option>',
			[
				{'value': '', 'label': 'Choose status'},
				{'value': 'Text fallback', 'label': 'Text fallback'},
				{'value': 'empty-label', 'label': 'Empty label fallback'},
				{'value': 'missing-label', 'label': 'Missing label fallback'},
				{'value': '', 'label': ''},
			],
			id='empty-values-and-label-fallbacks',
		),
	],
)
async def test_disabled_multiple_select_preserves_selected_values_and_labels(
	select_browser: BrowserSession,
	select_server: HTTPServer,
	options: str,
	expected_selection: list[dict[str, str]],
):
	"""Only live selected options contribute, with native value and displayed label semantics."""
	await _open_form(
		select_browser,
		select_server,
		f'<select id="status" name="status" multiple size="7" disabled>{options}</select>',
	)
	session = await select_browser.get_or_create_cdp_session()
	readback = await session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': "Array.from(document.querySelector('select').selectedOptions, option => ({value: option.value, label: option.label || option.text}))",
			'returnByValue': True,
		},
		session_id=session.session_id,
	)
	assert readback['result'].get('value') == expected_selection
	state = await _dom_state(select_browser)
	assert _reported_selection(state) == expected_selection
	_assert_disabled_controls_not_indexed(state)


async def test_enabled_select_remains_indexed_and_can_change_selection(select_browser: BrowserSession, select_server: HTTPServer):
	"""Exposing disabled values must preserve the normal dropdown action path."""
	await _open_form(
		select_browser,
		select_server,
		'<select id="status" name="status">'
		'<option value="draft" selected>Draft</option>'
		'<option value="active">Active</option></select>',
	)
	state = await _dom_state(select_browser)
	indices = [index for index, node in state.selector_map.items() if node.attributes.get('id') == 'status']
	assert len(indices) == 1, state.llm_representation()
	result = await Tools().select_dropdown(index=indices[0], text='Active', browser_session=select_browser)
	assert result.error is None, result.error
	updated_state = await _dom_state(select_browser)
	assert any(node.attributes.get('id') == 'status' for node in updated_state.selector_map.values())
	assert _reported_selection(updated_state) == [{'value': 'active', 'label': 'Active'}]


@pytest.mark.parametrize(
	('prefix', 'attributes', 'suffix'),
	[
		pytest.param('', 'hidden', '', id='hidden-attribute'),
		pytest.param('', 'style="display: none"', '', id='display-none'),
		pytest.param('', 'style="visibility: hidden"', '', id='visibility-hidden'),
		pytest.param('<div hidden>', '', '</div>', id='hidden-ancestor'),
	],
)
async def test_hidden_disabled_select_does_not_expose_values_or_indices(
	select_browser: BrowserSession,
	select_server: HTTPServer,
	prefix: str,
	attributes: str,
	suffix: str,
):
	"""The visible-value exception must not leak hidden controls or their option text."""
	await _open_form(
		select_browser,
		select_server,
		f'{prefix}<select id="hidden-status" name="hidden-status" disabled {attributes}>'
		'<option value="hidden-choice" label="Hidden selected label">Hidden option text</option>'
		f'</select>{suffix}',
	)
	state = await _dom_state(select_browser)
	serialized = state.llm_representation()
	for hidden_content in ('hidden-status', 'hidden-choice', 'Hidden selected label', 'Hidden option text'):
		assert hidden_content not in serialized, serialized
	assert all(node.tag_name.lower() not in {'select', 'option', 'optgroup'} for node in state.selector_map.values())
