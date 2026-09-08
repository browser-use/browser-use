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
	lines = state.llm_representation().splitlines()
	select_position = next(index for index, line in enumerate(lines) if '<select' in line)
	select_line = lines[select_position]
	assert 'disabled' in select_line
	select_depth = len(select_line) - len(select_line.lstrip('\t'))
	if select_position + 1 < len(lines):
		next_line = lines[select_position + 1]
		assert len(next_line) - len(next_line.lstrip('\t')) <= select_depth, (
			f'Disabled select state must not be followed by duplicate option/selectedcontent text: {state.llm_representation()}'
		)


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


@pytest.mark.parametrize('customizable', [False, True], ids=['native', 'customizable'])
async def test_disabled_select_serializes_only_its_current_selection(
	select_browser: BrowserSession, select_server: HTTPServer, customizable: bool
):
	"""Rendered selectedcontent must not repeat the selection or expose unselected labels."""
	style = '<style>select, select::picker(select) { appearance: base-select; }</style>' if customizable else ''
	button = '<button><selectedcontent></selectedcontent></button>' if customizable else ''
	await _open_form(
		select_browser,
		select_server,
		f'{style}<select id="status" disabled>{button}'
		'<option value="alpha">Alpha label</option>'
		'<option value="beta" selected>Beta label</option>'
		'<option value="gamma">Gamma label</option></select>',
	)
	if customizable:
		session = await select_browser.get_or_create_cdp_session()
		readback = await session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': """(() => {
					const selected = document.querySelector('selectedcontent');
					return {appearance: getComputedStyle(document.querySelector('select')).appearance,
						text: selected.textContent, height: selected.getBoundingClientRect().height};
				})()""",
				'returnByValue': True,
			},
			session_id=session.session_id,
		)
		value = readback['result'].get('value') or {}
		if value.get('appearance') != 'base-select':
			pytest.skip('This browser does not support customizable select rendering')
		assert value['text'] == 'Beta label' and value['height'] > 0
	state = await _dom_state(select_browser)
	assert _reported_selection(state) == [{'value': 'beta', 'label': 'Beta label'}]
	serialized = state.llm_representation()
	assert serialized.count('Beta label') == 1, serialized
	assert 'Alpha label' not in serialized and 'Gamma label' not in serialized, serialized
	_assert_disabled_controls_not_indexed(state)


@pytest.mark.parametrize('inside_first_legend', [False, True], ids=['inherited-disabled', 'first-legend-exception'])
async def test_fieldset_disabled_select_respects_the_first_legend_exception(
	select_browser: BrowserSession, select_server: HTTPServer, inside_first_legend: bool
):
	"""Use the browser's inherited disabled state without disabling the first legend's control."""
	select = '<select id="status"><option value="draft" selected>Draft</option><option value="active">Active</option></select>'
	fieldset = (
		f'<fieldset disabled><legend>Status {select}</legend></fieldset>'
		if inside_first_legend
		else f'<fieldset disabled><legend>Status</legend>{select}</fieldset>'
	)
	await _open_form(select_browser, select_server, fieldset)
	session = await select_browser.get_or_create_cdp_session()
	readback = await session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': "document.querySelector('select').matches(':disabled')",
			'returnByValue': True,
		},
		session_id=session.session_id,
	)
	assert readback['result'].get('value') is not inside_first_legend
	state = await _dom_state(select_browser)
	assert _reported_selection(state) == [{'value': 'draft', 'label': 'Draft'}]
	if inside_first_legend:
		index = next(index for index, node in state.selector_map.items() if node.attributes.get('id') == 'status')
		result = await Tools().select_dropdown(index=index, text='Active', browser_session=select_browser)
		assert result.error is None, result.error
		assert _reported_selection(await _dom_state(select_browser)) == [{'value': 'active', 'label': 'Active'}]
	else:
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


async def test_offscreen_enabled_scrollable_select_keeps_its_action_index_in_output(
	select_browser: BrowserSession, select_server: HTTPServer
):
	"""Viewport filtering must not erase an enabled dropdown that was deliberately indexed."""
	options = ''.join(f'<option value="{index}">Choice {index}</option>' for index in range(20))
	await _open_form(
		select_browser,
		select_server,
		f'<select id="offscreen-status" size="4" style="position: absolute; top: 3000px">{options}</select>',
	)
	state = await _dom_state(select_browser)
	indexed = [(index, node) for index, node in state.selector_map.items() if node.attributes.get('id') == 'offscreen-status']
	assert len(indexed) == 1, state.llm_representation()
	index, original = indexed[0]
	assert original.snapshot_node is not None
	assert original.is_visible is False
	assert original.is_actually_scrollable is True
	select_lines = [line for line in state.llm_representation().splitlines() if '<select' in line]
	assert len(select_lines) == 1, state.llm_representation()
	assert f'[{index}]' in select_lines[0], select_lines[0]

	result = await Tools().select_dropdown(index=index, text='Choice 7', browser_session=select_browser)
	assert result.error is None, result.error
	# The action scrolls this control into view, so the top-of-page button may be offscreen.
	updated_summary = await select_browser.get_browser_state_summary(
		include_screenshot=False, include_recent_events=False, cached=False
	)
	updated_state = updated_summary.dom_state
	assert _reported_selection(updated_state) == [{'value': '7', 'label': 'Choice 7'}]
	updated_indices = [
		index for index, node in updated_state.selector_map.items() if node.attributes.get('id') == 'offscreen-status'
	]
	assert len(updated_indices) == 1
	updated_line = next(line for line in updated_state.llm_representation().splitlines() if '<select' in line)
	assert f'[{updated_indices[0]}]' in updated_line, updated_line


@pytest.mark.parametrize(
	('prefix', 'attributes', 'suffix'),
	[
		pytest.param('', 'style="opacity: 0"', '', id='opacity-zero'),
		pytest.param('', 'style="visibility: hidden"', '', id='visibility-hidden'),
		pytest.param('<div hidden>', '', '</div>', id='hidden-ancestor'),
		pytest.param('<div style="opacity: 0">', '', '</div>', id='opacity-zero-ancestor'),
	],
)
async def test_css_hidden_enabled_scrollable_select_does_not_expose_values(
	select_browser: BrowserSession,
	select_server: HTTPServer,
	prefix: str,
	attributes: str,
	suffix: str,
):
	"""Preserving indexed scrollable dropdowns must not expose CSS-hidden selection data."""
	options = ''.join(
		f'<option value="hidden-choice-{index}" label="Hidden choice {index}"'
		f'{" selected" if index == 0 else ""}>Hidden internal option {index}</option>'
		for index in range(20)
	)
	await _open_form(
		select_browser,
		select_server,
		f'{prefix}<select id="hidden-scrollable-status" multiple size="4" {attributes}>{options}</select>{suffix}',
	)
	state = await _dom_state(select_browser)
	serialized = state.llm_representation()
	for hidden_content in ('hidden-scrollable-status', 'hidden-choice-', 'Hidden choice', 'Hidden internal option'):
		assert hidden_content not in serialized, serialized
