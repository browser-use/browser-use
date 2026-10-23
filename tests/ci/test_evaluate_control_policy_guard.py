"""Real Chromium coverage for evaluate control and request policy enforcement."""

import asyncio
import json
import os
from unittest.mock import AsyncMock

import anyio
import pytest
from pydantic import BaseModel

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.views import HistoryItem
from browser_use.agent.views import (
	ActionResult,
	AgentHistory,
	AgentHistoryList,
	AgentOutput,
	AgentStepInfo,
	AmbiguousPolicyTransition,
	BrowserStateHistory,
	ConfirmedPolicyViolation,
	ControlStateChangeObservation,
	MessageCompactionSettings,
)
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm import BaseChatModel, SystemMessage
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.tools.evaluate_policy import (
	_GUARD_BOOTSTRAP,
	compare_control_snapshots,
	enforcement_unavailable_since,
	violations_since,
)
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools


@pytest.fixture
async def policy_browser_session():
	"""Start local Chromium without optional extension downloads."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			executable_path=os.getenv('BROWSER_USE_TEST_BROWSER_EXECUTABLE'),
			headless=True,
			args=['--disable-gpu', '--in-process-gpu', '--disable-gpu-sandbox'],
			user_data_dir=None,
			keep_alive=True,
			enable_default_extensions=False,
		)
	)
	try:
		await session.start()
		yield session
	finally:
		try:
			await session.kill()
		finally:
			await session.event_bus.stop(clear=True, timeout=5)


async def _evaluate_page(httpserver, session: BrowserSession, html: str, code: str, tools: Tools | None = None):
	httpserver.expect_request('/').respond_with_data(html, content_type='text/html')
	tools = tools or Tools()
	navigation = await tools.navigate(url=httpserver.url_for('/'), new_tab=False, browser_session=session)
	assert navigation.error is None, navigation.error
	return await tools.evaluate(code=code, browser_session=session), tools


async def _page_evaluate(session: BrowserSession, expression: str):
	cdp_session = await session.get_or_create_cdp_session()
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': expression, 'returnByValue': True, 'awaitPromise': True},
		session_id=cdp_session.session_id,
	)
	assert not result.get('exceptionDetails'), result.get('exceptionDetails')
	return result.get('result', {}).get('value')


def _request_count(httpserver, path: str, method: str) -> int:
	return sum(1 for request, _response in httpserver.log if request.path == path and request.method == method)


async def test_disabled_property_write_is_blocked_before_click(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="place" disabled onclick="document.body.dataset.clicked = \'yes\'">Place</button>',
		"(() => { const button = document.querySelector('#place'); let caught = false; try { button.disabled = false; } catch (_) { caught = true; } button.click(); return `${caught}:${button.disabled}:${document.body.dataset.clicked || ''}`; })()",
	)

	assert result.extracted_content == 'true:true:'
	assert [item.code for item in result.policy_violations] == ['disabled_control_bypass']
	assert await _page_evaluate(policy_browser_session, "document.querySelector('#place').disabled") is True
	assert await _page_evaluate(policy_browser_session, "document.body.dataset.clicked || ''") == ''


async def test_remove_disabled_attribute_is_blocked(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="place" disabled>Place</button>',
		"(() => { const button = document.querySelector('#place'); try { button.removeAttribute('disabled'); } catch (_) {} return button.hasAttribute('disabled'); })()",
	)

	assert result.extracted_content == 'True'
	assert [item.code for item in result.policy_violations] == ['disabled_control_bypass']


@pytest.mark.parametrize(
	'mutation',
	[
		"button.attributes.removeNamedItem('disabled')",
		"button.removeAttributeNode(button.getAttributeNode('disabled'))",
		"button.toggleAttribute('disabled', false)",
	],
)
async def test_disabled_attribute_removal_apis_are_blocked(httpserver, policy_browser_session, mutation):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="place" disabled>Place</button>',
		f"(() => {{ const button = document.querySelector('#place'); try {{ {mutation}; }} catch (_) {{}} return button.hasAttribute('disabled'); }})()",
	)

	assert result.extracted_content == 'True'
	assert [item.code for item in result.policy_violations] == ['disabled_control_bypass']


async def test_readonly_property_write_is_blocked(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<textarea id="notes" readonly>fixed</textarea>',
		"(() => { const input = document.querySelector('#notes'); try { input.readOnly = false; } catch (_) {} return `${input.readOnly}:${input.hasAttribute('readonly')}`; })()",
	)

	assert result.extracted_content == 'true:true'
	assert [item.code for item in result.policy_violations] == ['readonly_control_bypass']


@pytest.mark.parametrize(
	'write_expression',
	[
		"input.value = 'prohibited';",
		"input.setRangeText('prohibited', 0, input.value.length, 'select');",
		"input.defaultValue = 'prohibited';",
		"input.setAttribute('value', 'prohibited');",
		"input.setAttributeNS(null, 'value', 'prohibited');",
		"input.setAttributeNode(document.createAttribute('value'));",
		"input.setAttributeNodeNS(document.createAttributeNS(null, 'value'));",
		"input.attributes.setNamedItem(document.createAttribute('value'));",
		"input.attributes.setNamedItemNS(document.createAttributeNS(null, 'value'));",
		"input.getAttributeNode('value').value = 'prohibited';",
		"input.getAttributeNode('value').nodeValue = 'prohibited';",
		"input.getAttributeNode('value').textContent = 'prohibited';",
		"input.removeAttribute('value');",
		"input.toggleAttribute('value', false);",
	],
)
async def test_readonly_value_write_is_blocked_and_cannot_finalize_as_success(
	httpserver, policy_browser_session, tmp_path, write_expression
):
	result, tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<input id="name" readonly value="fixed">',
		f"(() => {{ const input = document.querySelector('#name'); try {{ {write_expression} }} catch (_) {{}} return input.value; }})()",
	)

	assert result.extracted_content == 'fixed'
	assert [item.code for item in result.policy_violations] == ['readonly_control_bypass']
	assert await _page_evaluate(policy_browser_session, "document.querySelector('#name').value") == 'fixed'
	completion = await tools.done(
		text='The readonly field was updated.',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.success is False
	assert 'blocked prohibited evaluate attempt' in (completion.extracted_content or '')


async def test_readonly_textarea_value_write_is_blocked(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<textarea id="notes" readonly>fixed</textarea>',
		"(() => { const notes = document.querySelector('#notes'); try { notes.value = 'prohibited'; } catch (_) {} return notes.value; })()",
	)
	assert result.extracted_content == 'fixed'
	assert [item.code for item in result.policy_violations] == ['readonly_control_bypass']


@pytest.mark.parametrize(
	('markup', 'write_expression', 'original_value'),
	[
		('<input id="name" type="number" readonly value="2">', 'input.valueAsNumber = 7;', '2'),
		(
			'<input id="name" type="date" readonly value="2020-01-01">',
			"input.valueAsDate = new Date('2022-01-01T00:00:00Z');",
			'2020-01-01',
		),
		('<input id="name" type="number" readonly value="2">', 'input.stepUp();', '2'),
	],
)
async def test_readonly_specialized_value_apis_are_blocked(
	httpserver, policy_browser_session, markup, write_expression, original_value
):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		markup,
		f"(() => {{ const input = document.querySelector('#name'); try {{ {write_expression} }} catch (_) {{}} return input.value; }})()",
	)
	assert result.extracted_content == original_value
	assert [item.code for item in result.policy_violations] == ['readonly_control_bypass']


async def test_form_reset_cannot_change_readonly_value_or_finalize_as_success(httpserver, policy_browser_session, tmp_path):
	result, tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		"<form id='form'><input id='name' readonly value='initial'></form><script>document.querySelector('#name').value='page-value';</script>",
		"(() => { try { document.querySelector('#form').reset(); } catch (_) {} return document.querySelector('#name').value; })()",
	)
	assert result.extracted_content == 'page-value'
	assert [item.code for item in result.policy_violations] == ['readonly_control_bypass']
	completion = await tools.done(
		text='The readonly field was reset.',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.success is False


async def test_form_reset_without_restricted_controls_remains_allowed(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		"<form id='form'><input id='name' value='initial'><button disabled value='submit'>Submit</button></form><script>document.querySelector('#name').value='changed';</script>",
		"(() => { document.querySelector('#form').reset(); return document.querySelector('#name').value; })()",
	)
	assert result.extracted_content == 'initial'
	assert result.policy_violations == []
	assert result.policy_enforcement_unavailable is False


async def test_readonly_attribute_removal_is_blocked(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<input id="name" readonly value="locked">',
		"(() => { const input = document.querySelector('#name'); try { input.removeAttribute('readonly'); } catch (_) {} return input.hasAttribute('readonly'); })()",
	)

	assert result.extracted_content == 'True'
	assert [item.code for item in result.policy_violations] == ['readonly_control_bypass']


async def test_same_evaluate_cannot_enable_and_click_disabled_button(httpserver, policy_browser_session):
	httpserver.expect_request('/api/order', method='POST').respond_with_data('{"ok":true}')
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		"<button id=\"place\" disabled onclick=\"fetch('/api/order', {method:'POST'}); document.body.dataset.clicked='yes'\">Place</button>",
		"(() => { const button = document.querySelector('#place'); try { button.disabled = false; } catch (_) {} button.click(); return `${button.disabled}:${document.body.dataset.clicked || ''}`; })()",
	)

	assert result.extracted_content == 'true:'
	assert [item.code for item in result.policy_violations] == ['disabled_control_bypass']
	assert _request_count(httpserver, '/api/order', 'POST') == 0


async def test_later_click_cannot_clear_sticky_violation(httpserver, policy_browser_session, tmp_path):
	result, tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="place" disabled>Place</button>',
		"try { document.querySelector('#place').disabled = false; } catch (_) {} 'attempted'",
	)
	assert result.policy_violations

	click_result = await tools.click(index=1, browser_session=policy_browser_session)
	assert click_result.error is not None
	assert 'earlier evaluate attempt' in click_result.error

	completion = await tools.done(
		text='The order was placed.',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.is_done is True
	assert completion.success is False
	assert 'blocked prohibited evaluate attempt' in (completion.extracted_content or '')


async def test_evaluate_post_request_is_blocked_without_network_dispatch(httpserver, policy_browser_session):
	httpserver.expect_request('/api/order', method='POST').respond_with_data('{"ok":true}')
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<main>Order page</main>',
		"(() => { try { fetch('/api/order', {method: 'POST', body: 'item=blue-mug'}); } catch (_) { return 'blocked'; } return 'sent'; })()",
	)

	assert result.extracted_content == 'blocked'
	assert [item.code for item in result.policy_violations] == ['direct_state_change_request']
	assert _request_count(httpserver, '/api/order', 'POST') == 0


@pytest.mark.parametrize('initial_method,reopen_method', [('POST', 'GET'), ('GET', 'POST')])
async def test_failed_xhr_open_preserves_the_actual_request_method(
	httpserver, policy_browser_session, initial_method, reopen_method
):
	httpserver.expect_request('/api/request', method=initial_method).respond_with_data('ok')
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<main>Request fixture</main>',
		f"new Promise(resolve => {{ const xhr=new XMLHttpRequest(); xhr.open('{initial_method}','/api/request'); let failed=false; try {{ xhr.open('{reopen_method}','http://['); }} catch (_) {{ failed=true; }} xhr.onload=()=>resolve(failed+':response:'+xhr.responseText); xhr.onerror=()=>resolve('network error'); try {{ xhr.send(); }} catch (_) {{ resolve(failed+':blocked'); }} }})",
	)
	if initial_method == 'POST':
		assert result.extracted_content == 'true:blocked'
		assert [item.code for item in result.policy_violations] == ['direct_state_change_request']
		assert _request_count(httpserver, '/api/request', 'POST') == 0
	else:
		assert result.extracted_content == 'true:response:ok'
		assert result.policy_violations == []
		assert _request_count(httpserver, '/api/request', 'GET') == 1


async def test_page_world_cannot_tamper_with_isolated_guard(httpserver, policy_browser_session):
	html = """<!doctype html>
<button id="place" disabled>Place</button>
<script>
Object.defineProperty(globalThis, '__browser_use_evaluate_policy_guard_v1__', {value: {readState: () => ({counts: {}, snapshot: {controls: []}})}});
const original = Object.getOwnPropertyDescriptor(HTMLButtonElement.prototype, 'disabled');
Object.defineProperty(HTMLButtonElement.prototype, 'disabled', {get: original.get, set() {}, configurable: true});
</script>"""
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		html,
		"(() => { let protected = false; try { Object.defineProperty(HTMLButtonElement.prototype, 'disabled', {set() {}}); } catch (_) { protected = true; } try { document.querySelector('#place').disabled = false; } catch (_) {} return `${protected}:${document.querySelector('#place').disabled}`; })()",
	)

	assert result.extracted_content == 'true:true'
	assert [item.code for item in result.policy_violations] == ['disabled_control_bypass']


async def test_shadow_dom_control_is_guarded(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		"<div id=\"host\"></div><script>const root=document.querySelector('#host').attachShadow({mode:'open'});root.innerHTML='<button id=\"place\" disabled>Place</button>';</script>",
		"(() => { const button = document.querySelector('#host').shadowRoot.querySelector('#place'); try { button.disabled = false; } catch (_) {} return button.disabled; })()",
	)

	assert result.extracted_content == 'True'
	assert [item.code for item in result.policy_violations] == ['disabled_control_bypass']


async def test_shadow_dom_replacement_is_guarded(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		"<div id=\"host\"></div><script>document.querySelector('#host').attachShadow({mode:'open'}).innerHTML='<button disabled>Place</button>';</script>",
		"(() => { const root = document.querySelector('#host').shadowRoot; try { root.innerHTML = ''; } catch (_) {} return Boolean(root.querySelector('button')); })()",
	)

	assert result.extracted_content == 'True'
	assert [item.code for item in result.policy_violations] == ['restricted_control_replacement']


async def test_restricted_node_replacement_is_blocked(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<section id="container"><button id="place" disabled>Place</button></section>',
		"(() => { const button = document.querySelector('#place'); try { button.replaceWith(document.createElement('button')); } catch (_) {} return Boolean(document.querySelector('#place')); })()",
	)

	assert result.extracted_content == 'True'
	assert [item.code for item in result.policy_violations] == ['restricted_control_replacement']


async def test_inherited_disabled_control_cannot_be_moved_out_of_fieldset(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<fieldset disabled><button id="place">Place</button></fieldset><div id="destination"></div>',
		"(() => { const button = document.querySelector('#place'); try { document.querySelector('#destination').appendChild(button); } catch (_) {} return button.parentElement.tagName + ':' + button.matches(':disabled'); })()",
	)

	assert result.extracted_content == 'FIELDSET:true'
	assert [item.code for item in result.policy_violations] == ['disabled_control_transfer']


@pytest.mark.parametrize(
	'clone_expression',
	[
		'button.cloneNode(true)',
		'document.importNode(button, true)',
		'(() => { const range = document.createRange(); range.selectNode(button); return range.cloneContents(); })()',
	],
)
async def test_inherited_disabled_control_cannot_be_duplicated_out_of_fieldset(
	httpserver, policy_browser_session, clone_expression
):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<fieldset disabled><button id="place">Place</button></fieldset><div id="destination"></div>',
		f"(() => {{ const button = document.querySelector('#place'); try {{ document.querySelector('#destination').appendChild({clone_expression}); }} catch (_) {{}} return document.querySelector('#destination').childElementCount + ':' + button.matches(':disabled'); }})()",
	)

	assert result.extracted_content == '0:true'
	assert [item.code for item in result.policy_violations] == ['disabled_control_duplication']


async def test_cloning_disabled_fieldset_preserves_its_restriction(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<div id="destination"></div><fieldset id="source" disabled><button>Place</button></fieldset>',
		"(() => { const source = document.querySelector('#source'); const range = document.createRange(); range.selectNode(source); document.querySelector('#destination').appendChild(range.cloneContents()); return document.querySelector('#destination button').matches(':disabled'); })()",
	)

	assert result.extracted_content == 'True'
	assert result.policy_violations == []


async def test_range_deletion_cannot_remove_a_restricted_control(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="place" disabled>Place</button>',
		"(() => { const range = document.createRange(); range.selectNode(document.querySelector('#place')); try { range.deleteContents(); } catch (_) {} return Boolean(document.querySelector('#place')); })()",
	)

	assert result.extracted_content == 'True'
	assert [item.code for item in result.policy_violations] == ['restricted_control_replacement']


async def test_same_origin_iframe_with_restricted_control_fails_closed(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<iframe id="child" srcdoc="&lt;button disabled&gt;Place&lt;/button&gt;"></iframe>',
		"document.querySelector('#child').contentDocument.querySelector('button').disabled = false",
	)

	assert result.error is not None
	assert 'nested frame' in result.error
	assert result.policy_violations == []


async def test_compliant_user_input_can_enable_control_without_violation(httpserver, policy_browser_session):
	result, tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		"""<!doctype html><input id="name"><button id="submit" disabled>Submit</button>
<script>document.querySelector('#name').addEventListener('input', () => { document.querySelector('#submit').disabled = false; });</script>""",
		"document.querySelector('#submit').disabled",
	)
	assert result.extracted_content == 'True'

	await _page_evaluate(policy_browser_session, "document.querySelector('#name').focus()")
	cdp_session = await policy_browser_session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Input.insertText(
		params={'text': 'valid name'},
		session_id=cdp_session.session_id,
	)
	assert await _page_evaluate(policy_browser_session, "document.querySelector('#submit').disabled") is False

	read_result = await tools.evaluate(
		code="document.querySelector('#submit').disabled",
		browser_session=policy_browser_session,
	)
	assert read_result.extracted_content == 'False'
	assert read_result.policy_violations == []
	assert read_result.ambiguous_policy_transitions == []
	assert read_result.policy_enforcement_unavailable is False


async def test_editable_input_evaluation_without_restricted_transition_remains_allowed(
	httpserver, policy_browser_session, tmp_path
):
	result, tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<input id="name" value="initial">',
		"(() => { const input=document.querySelector('#name'); input.value='updated'; return input.value; })()",
	)
	assert result.extracted_content == 'updated'
	assert result.policy_violations == []
	assert result.ambiguous_policy_transitions == []
	assert result.policy_enforcement_unavailable is False

	completion = await tools.done(
		text='Updated the editable field.',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.success is True


async def test_javascript_result_and_exception_are_preserved(httpserver, policy_browser_session):
	result, tools = await _evaluate_page(httpserver, policy_browser_session, '<main>Ready</main>', "'original result'")
	assert result.extracted_content == 'original result'
	boolean = await tools.evaluate(code='true', browser_session=policy_browser_session)
	assert boolean.extracted_content == 'True'  # Preserve evaluate's existing Python str(bool) contract.

	error = await tools.evaluate(
		code="(() => { throw new Error('original evaluation error'); })()",
		browser_session=policy_browser_session,
	)
	assert error.error is not None
	assert 'original evaluation error' in error.error
	assert error.policy_violations == []


async def test_evaluate_cdp_error_is_classified_as_unverified(httpserver, policy_browser_session, monkeypatch, tmp_path):
	tools = Tools()
	await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button>Continue</button>',
		'document.title',
		tools=tools,
	)
	cdp_session = await policy_browser_session.get_or_create_cdp_session()
	client = cdp_session.cdp_client
	original_send_raw = client.send_raw
	expression = "document.body.dataset.ran='yes'; 'transport-error-sentinel'"

	async def fail_evaluate_request(method, params=None, session_id=None):
		if method == 'Runtime.evaluate' and params and params.get('expression') == expression:
			raise RuntimeError('CDP disconnected')
		return await original_send_raw(method=method, params=params, session_id=session_id)

	monkeypatch.setattr(client, 'send_raw', fail_evaluate_request)
	result = await tools.evaluate(code=expression, browser_session=policy_browser_session)

	assert result.error is not None and 'CDP disconnected' in result.error
	assert result.policy_enforcement_unavailable is True
	assert result.policy_violations == []
	assert await _page_evaluate(policy_browser_session, "document.body.dataset.ran || ''") == ''
	blocked = await tools.click(index=1, browser_session=policy_browser_session)
	assert blocked.policy_enforcement_unavailable is True
	completion = await tools.done(
		text='Completed.',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.success is False
	assert completion.policy_enforcement_unavailable is True


async def test_registry_cdp_dependency_failure_is_unavailable():
	tools = Tools()
	session = BrowserSession()
	result = await tools.evaluate(code='1', browser_session=session)
	assert result.error is not None and 'CDP client not initialized' in result.error
	assert result.policy_enforcement_unavailable is True
	assert result.policy_violations == []
	blocked = await tools.click(index=1, browser_session=session)
	assert blocked.policy_enforcement_unavailable is True


async def test_unstructured_done_preserves_calls_without_browser_session(tmp_path):
	result = await Tools().done(
		text='Completed',
		success=True,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert result.is_done is True
	assert result.success is True
	assert result.error is None
	assert result.extracted_content == 'Completed'


async def test_action_timeout_records_unavailable_and_blocks_followup(httpserver, policy_browser_session, tmp_path):
	_, tools = await _evaluate_page(httpserver, policy_browser_session, '<button>Continue</button>', 'document.title')
	action_model = tools.registry.create_action_model(include_actions=['evaluate']).model_validate(
		{'evaluate': {'code': 'new Promise(() => {})'}}
	)
	result = await tools.act(action_model, browser_session=policy_browser_session, action_timeout=1.0)

	assert result.policy_enforcement_unavailable is True
	assert result.error is not None and 'timed out' in result.error
	click_model = tools.registry.create_action_model(include_actions=['click']).model_validate({'click': {'index': 1}})
	blocked = await tools.act(click_model, browser_session=policy_browser_session)
	assert blocked.policy_enforcement_unavailable is True
	assert blocked.error is not None and 'could not be verified' in blocked.error
	completion = await tools.done(
		text='The page was handled.',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.success is False
	assert completion.policy_enforcement_unavailable is True


async def test_cancelled_evaluate_cleans_real_cdp_request_and_fails_closed(httpserver, policy_browser_session, monkeypatch):
	_, tools = await _evaluate_page(httpserver, policy_browser_session, '<main>Ready</main>', 'document.title')
	cdp_session = await policy_browser_session.get_or_create_cdp_session()
	client = cdp_session.cdp_client
	original_send_raw = client.send_raw
	expression = (
		'new Promise(resolve => setTimeout(() => '
		'(globalThis.__browser_use_cancelled_evaluate_finished = true, resolve("late")), 5000))'
	)
	request_id: int | None = None
	request_started = asyncio.Event()

	async def tracked_send_raw(method, params=None, session_id=None):
		nonlocal request_id
		if method == 'Runtime.evaluate' and params and params.get('expression') == expression:
			request_id = int(client.msg_id) + 1
			request_started.set()
		return await original_send_raw(method=method, params=params, session_id=session_id)

	monkeypatch.setattr(client, 'send_raw', tracked_send_raw)
	task = asyncio.create_task(tools.evaluate(code=expression, browser_session=policy_browser_session))
	await asyncio.wait_for(request_started.wait(), timeout=3)
	assert request_id is not None
	deadline = asyncio.get_running_loop().time() + 2
	while request_id not in client.pending_requests and asyncio.get_running_loop().time() < deadline:  # noqa: ASYNC110 - CDP exposes a pending-request map without an awaitable notification
		await anyio.sleep(0.01)
	assert request_id in client.pending_requests
	task.cancel()
	with pytest.raises(asyncio.CancelledError):
		await task
	assert request_id not in client.pending_requests

	blocked = await tools.click(index=1, browser_session=policy_browser_session)
	assert blocked.policy_enforcement_unavailable is True
	assert blocked.error is not None and 'could not be verified' in blocked.error

	context = await tools._evaluate_policy_guard.context_for(cdp_session)
	assert context is not None
	deadline = asyncio.get_running_loop().time() + 7
	while True:
		late = await client.send.Runtime.evaluate(
			params={
				'expression': 'this.__browser_use_cancelled_evaluate_finished === true',
				'contextId': context[1],
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)
		if late.get('result', {}).get('value') is True:
			break
		assert asyncio.get_running_loop().time() < deadline, 'Cancelled browser evaluation did not finish before the deadline'
		await anyio.sleep(0.05)
	assert request_id not in client.pending_requests


@pytest.mark.parametrize('method', ['append', 'prepend', 'before', 'after'])
async def test_variadic_transfer_does_not_swallow_its_own_block(httpserver, policy_browser_session, method):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<fieldset disabled><button id="place" onclick="document.body.dataset.clicked=1">Place</button></fieldset><div id="destination"></div>',
		f"(() => {{ const button=document.querySelector('#place'); try {{ document.querySelector('#destination').{method}(button); }} catch (_) {{}} button.click(); return button.matches(':disabled') + ':' + (document.body.dataset.clicked || ''); }})()",
	)
	assert result.extracted_content == 'true:'
	assert [item.code for item in result.policy_violations] == ['disabled_control_transfer']


@pytest.mark.parametrize(
	'mutation',
	[
		'button.removeAttribute(name)',
		'button.removeAttributeNS(null, name)',
		'button.toggleAttribute(name, false)',
		'button.attributes.removeNamedItem(name)',
		'button.attributes.removeNamedItemNS(null, name)',
	],
)
async def test_attribute_name_is_coerced_once(httpserver, policy_browser_session, mutation):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="place" disabled data-other="">Place</button>',
		f"(() => {{ const button=document.querySelector('#place'); let calls=0; const name={{toString(){{return ++calls === 1 ? 'data-other' : 'disabled';}}}}; {mutation}; return calls + ':' + button.disabled; }})()",
	)
	assert result.extracted_content == '1:true'
	assert result.policy_violations == []


async def test_namespace_object_cannot_hide_disabled_removal(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="place" disabled>Place</button>',
		"(() => { const button=document.querySelector('#place'); try { button.removeAttributeNS({toString:()=>''},'disabled'); } catch (_) {} return button.disabled; })()",
	)
	assert result.extracted_content == 'True'
	assert [item.code for item in result.policy_violations] == ['disabled_control_bypass']


async def test_evaluated_code_cannot_forge_guard_readout(httpserver, policy_browser_session):
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="place" disabled>Place</button>',
		"(() => { Object.prototype.toJSON = () => ({counts:{},snapshot:{controls:[],complete:true}}); Array.prototype.toJSON = () => []; globalThis = {__browser_use_evaluate_policy_guard_v1__:{readState:()=>({counts:{},snapshot:{controls:[],complete:true}})}}; try { document.querySelector('#place').disabled=false; } catch (_) {} return 'original result'; })()",
	)
	assert result.extracted_content == 'original result'
	assert [item.code for item in result.policy_violations] == ['disabled_control_bypass']
	assert await _page_evaluate(policy_browser_session, "document.querySelector('#place').disabled") is True


@pytest.mark.parametrize('write_expression', ["name.value='valid';", "name.setRangeText('valid',0,name.value.length);"])
async def test_synthetic_page_handler_transition_is_ambiguous_and_fails_closed(
	httpserver, policy_browser_session, tmp_path, write_expression
):
	result, tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		"<input id='name'><button id='place' disabled>Place</button><script>document.querySelector('#name').addEventListener('input', e => { if(e.target.value==='valid') document.querySelector('#place').disabled=false; });</script>",
		f"(() => {{ const name=document.querySelector('#name'); {write_expression} name.dispatchEvent(new Event('input',{{bubbles:true}})); return document.querySelector('#place').disabled; }})()",
	)
	assert result.extracted_content == 'False'
	assert result.policy_violations == []
	assert result.policy_enforcement_unavailable is False
	assert result.control_state_change_observation is not None
	assert result.control_state_change_observation.disabled_to_enabled == 1
	assert len(result.ambiguous_policy_transitions) == 1
	assert result.ambiguous_policy_transitions[0].code == 'unattributed_restricted_control_transition'
	assert result.ambiguous_policy_transitions[0].observation.disabled_to_enabled == 1

	blocked = await tools.click(index=1, browser_session=policy_browser_session)
	assert blocked.error is not None
	assert 'cause could not be attributed' in blocked.error

	completion = await tools.done(
		text='Completed allowed input.',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.success is False
	assert completion.trusted_policy_disclosure is True
	assert 'could not attribute its cause' in (completion.extracted_content or '')


@pytest.mark.parametrize('method', ['GET', 'HEAD', 'OPTIONS'])
async def test_direct_get_like_requests_remain_allowed(httpserver, policy_browser_session, method):
	httpserver.expect_request('/api/read', method=method).respond_with_data('allowed')
	result, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<main>Read</main>',
		f"fetch('/api/read',{{method:'{method}'}}).then(response=>response.status)",
	)
	assert result.extracted_content == '200'
	assert result.policy_violations == []
	assert _request_count(httpserver, '/api/read', method) == 1


async def test_dynamic_frame_is_reported_unavailable_and_stops_followup(httpserver, policy_browser_session):
	result, tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<main>No frames</main>',
		"document.body.appendChild(document.createElement('iframe')); 'frame created'",
	)
	assert result.extracted_content == 'frame created'
	assert result.policy_enforcement_unavailable is True
	assert result.policy_violations == []
	blocked = await tools.click(index=1, browser_session=policy_browser_session)
	assert blocked.policy_enforcement_unavailable is True


async def test_guard_initialization_failure_never_runs_code_and_is_sticky(
	httpserver, policy_browser_session, monkeypatch, tmp_path
):
	tools = Tools()
	await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<main id="target">ready</main>',
		'document.title',
		tools=tools,
	)
	cdp_session = await policy_browser_session.get_or_create_cdp_session()
	client = cdp_session.cdp_client
	original_send_raw = client.send_raw
	bootstrap_attempted = False

	async def fail_guard_bootstrap(method, params=None, session_id=None):
		nonlocal bootstrap_attempted
		if method == 'Runtime.evaluate' and params and params.get('expression') == _GUARD_BOOTSTRAP:
			bootstrap_attempted = True
			raise RuntimeError('injected CDP bootstrap failure')
		return await original_send_raw(method=method, params=params, session_id=session_id)

	monkeypatch.setattr(client, 'send_raw', fail_guard_bootstrap)
	result = await tools.evaluate(
		code="document.querySelector('#target').dataset.ran='yes'; 'executed'",
		browser_session=policy_browser_session,
	)
	assert result.policy_enforcement_unavailable is True
	assert result.policy_violations == []
	assert result.error is not None and 'injected CDP bootstrap failure' in result.error
	assert bootstrap_attempted is True
	assert await _page_evaluate(policy_browser_session, "document.querySelector('#target').dataset.ran || ''") == ''
	blocked = await tools.click(index=1, browser_session=policy_browser_session)
	assert blocked.policy_enforcement_unavailable is True
	completion = await tools.done(
		text='Done',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.success is False
	assert completion.policy_enforcement_unavailable is True


async def test_incomplete_snapshot_preserves_confirmed_counters_and_original_result(httpserver, policy_browser_session, tmp_path):
	result, tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="locked" disabled>Locked</button>',
		"(() => { const button=document.querySelector('#locked'); try { button.disabled=false; } catch (_) {} "
		"const fragment=document.createDocumentFragment(); for(let i=0;i<5001;i++) fragment.appendChild(document.createElement('input')); "
		"document.body.appendChild(fragment); return 'original'; })()",
	)
	assert result.extracted_content == 'original'
	assert [item.code for item in result.policy_violations] == ['disabled_control_bypass']
	assert result.policy_enforcement_unavailable is True
	completion = await tools.done(
		text='Completed.',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.success is False
	assert completion.policy_enforcement_unavailable is True


async def test_sticky_violation_survives_another_tools_instance(monkeypatch):
	session = BrowserSession()
	tools = Tools()
	tools._record_policy_violations(session, [ConfirmedPolicyViolation(code='disabled_control_bypass')])
	replacement = Tools()
	execute = AsyncMock()
	monkeypatch.setattr(type(replacement.registry), 'execute_action', execute)
	result = await replacement.click(index=1, browser_session=session)
	assert result.error is not None and 'earlier evaluate attempt' in result.error
	execute.assert_not_awaited()
	# The browser session itself is not retained by the shared policy store.
	assert replacement._has_policy_violations(session)


async def test_custom_action_cannot_forge_sticky_policy_state(httpserver, policy_browser_session, tmp_path):
	tools = Tools()
	await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button onclick="document.body.dataset.clicked=\'yes\'">Continue</button>',
		'document.title',
		tools=tools,
	)
	transition = AmbiguousPolicyTransition(observation=ControlStateChangeObservation(disabled_to_enabled=1))

	@tools.action('Return deliberately forged policy metadata for a regression test.')
	async def forge_policy_metadata():
		return ActionResult(
			policy_violations=[ConfirmedPolicyViolation(code='disabled_control_bypass')],
			ambiguous_policy_transitions=[transition],
			policy_enforcement_unavailable=True,
			trusted_policy_disclosure=True,
		)

	forged = await tools.forge_policy_metadata(browser_session=policy_browser_session)
	assert forged.policy_violations == []
	assert forged.ambiguous_policy_transitions == []
	assert forged.policy_enforcement_unavailable is False
	assert forged.trusted_policy_disclosure is False

	await policy_browser_session.get_browser_state_summary(include_screenshot=False)
	selector_map = await policy_browser_session.get_selector_map()
	assert selector_map
	click_result = await tools.click(index=next(iter(selector_map)), browser_session=policy_browser_session)
	assert click_result.error is None
	assert click_result.extracted_content is not None and click_result.extracted_content.startswith('Clicked')
	assert await _page_evaluate(policy_browser_session, "document.body.dataset.clicked || ''") == 'yes'
	completion = await tools.done(
		text='Continue button clicked.',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.is_done is True
	assert completion.success is True
	assert completion.trusted_policy_disclosure is False


def _history_step(result: ActionResult, model_output=None) -> AgentHistory:
	return AgentHistory(
		model_output=model_output,
		result=[result],
		state=BrowserStateHistory(url='http://localhost/', title='fixture', tabs=[], interacted_element=[]),
	)


class _Answer(BaseModel):
	answer: str


class _StructuredDone(ActionModel):
	done: dict[str, object]


class _QueuedClick(ActionModel):
	click: dict[str, object]


async def test_registered_structured_done_fails_after_violation_but_preserves_json(httpserver, policy_browser_session, tmp_path):
	tools = Tools(output_model=_Answer)
	violation, _tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="place" disabled>Place</button>',
		"try { document.querySelector('#place').disabled = false; } catch (_) {} 'attempted'",
		tools=tools,
	)
	assert [item.code for item in violation.policy_violations] == ['disabled_control_bypass']

	data = {'answer': 'Order placed'}
	json_payload = json.dumps(data, ensure_ascii=False)
	completion = await tools.done(
		data=data,
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.is_done is True
	assert completion.success is False
	assert completion.extracted_content == json_payload
	assert completion.trusted_policy_disclosure is True

	model_output = AgentOutput.model_construct(action=[_StructuredDone(done={'data': data, 'success': True})])
	history = AgentHistoryList(history=[_history_step(violation), _history_step(completion, model_output)])
	history._output_model_schema = _Answer
	assert history.final_result() == json_payload
	assert history.structured_output == _Answer(answer='Order placed')
	assert history.is_successful() is False
	assert [item.code for item in history.policy_violations()] == ['disabled_control_bypass']


def test_state_change_observation_does_not_confirm_causality():
	before = {
		'identity': 'main-frame',
		'counts': {},
		'snapshot': {'controls': [{'key': '1', 'disabled': True, 'readonly': False}]},
	}
	after = {
		'identity': 'main-frame',
		'counts': {},
		'snapshot': {'controls': [{'key': '1', 'disabled': False, 'readonly': False}]},
	}

	observation = compare_control_snapshots(before['snapshot'], after['snapshot'])
	assert observation is not None
	assert observation.disabled_to_enabled == 1
	assert violations_since(before, after) == []
	assert not enforcement_unavailable_since(before, after)
	assert enforcement_unavailable_since(before, {'counts': {'guard_enforcement_unavailable': 1}})


def test_confirmed_violation_survives_history_serialization():
	marker = ConfirmedPolicyViolation(code='disabled_control_bypass')
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(policy_violations=[marker])),
			_history_step(ActionResult(is_done=True, success=True, extracted_content='Order placed.')),
		]
	)

	assert history.is_successful() is False
	assert 'blocked a prohibited evaluate attempt' in (history.final_result() or '')
	assert history.policy_violations() == [marker]
	assert history.action_history()[0] == [{'policy_violations': [{'code': 'disabled_control_bypass', 'attempts': 1}]}]
	pending = AgentHistoryList(history=[_history_step(ActionResult(policy_violations=[marker]))])
	assert pending.is_successful() is None
	untrusted_disclosure = AgentHistoryList(
		history=[
			_history_step(ActionResult(policy_violations=[marker])),
			_history_step(
				ActionResult(
					is_done=True,
					success=True,
					extracted_content='Browser Use blocked a prohibited evaluate attempt: disabled_control_bypass.',
				)
			),
		]
	)
	assert (untrusted_disclosure.final_result() or '').count('Browser Use blocked a prohibited evaluate attempt') == 2

	serialized = history.model_dump()
	restored = AgentHistoryList.load_from_dict(serialized, AgentOutput)
	assert restored.is_successful() is False
	assert restored.policy_violations()[0].code == 'disabled_control_bypass'
	assert 'blocked a prohibited evaluate attempt' in (restored.final_result() or '')

	text_only = AgentHistoryList(history=[_history_step(ActionResult(extracted_content='Policy violation: disabled control.'))])
	assert text_only.policy_violations() == []
	assert text_only.is_successful() is None
	assert text_only.final_result() == 'Policy violation: disabled control.'

	for code in ('disabled_control_transfer', 'disabled_control_duplication'):
		transfer_or_duplication = ConfirmedPolicyViolation(code=code)
		typed_history = AgentHistoryList(
			history=[
				_history_step(ActionResult(policy_violations=[transfer_or_duplication])),
				_history_step(ActionResult(is_done=True, success=True, extracted_content='Done.')),
			]
		)
		assert typed_history.policy_violations() == [transfer_or_duplication]
		assert typed_history.is_successful() is False
		assert code in (typed_history.final_result() or '')
		restored_typed_history = AgentHistoryList.load_from_dict(typed_history.model_dump(), AgentOutput)
		assert restored_typed_history.policy_violations() == [transfer_or_duplication]


def test_final_result_is_none_without_completion_text_but_policy_api_remains_available():
	marker = ConfirmedPolicyViolation(code='disabled_control_bypass')
	history = AgentHistoryList(history=[_history_step(ActionResult(policy_violations=[marker]))])

	assert history.final_result() is None
	assert history.is_successful() is None
	assert history.policy_violations() == [marker]
	assert history.action_history() == [[{'policy_violations': [{'code': 'disabled_control_bypass', 'attempts': 1}]}]]


def test_structured_final_result_uses_done_result_that_actually_executed():
	marker = ConfirmedPolicyViolation(code='disabled_control_bypass')
	data = {'answer': 'submitted'}
	json_payload = json.dumps(data)
	model_output = AgentOutput.model_construct(
		action=[
			_StructuredDone(done={'data': data, 'success': False}),
			_QueuedClick(click={'index': 1}),
		]
	)
	completion = ActionResult(is_done=True, success=False, extracted_content=json_payload)
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(policy_violations=[marker])),
			_history_step(completion, model_output),
		]
	)

	assert len(history.history[-1].result) == 1  # The queued click was never executed after done.
	assert history._final_result_is_structured() is True
	assert history.final_result() == json_payload
	assert history.get_structured_output(_Answer) == _Answer(answer='submitted')
	assert history.is_successful() is False
	assert history.policy_violations() == [marker]


def test_ambiguous_transition_is_typed_separately_from_confirmed_violation():
	transition = AmbiguousPolicyTransition(
		observation=ControlStateChangeObservation(disabled_to_enabled=1),
	)
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(ambiguous_policy_transitions=[transition])),
			_history_step(ActionResult(is_done=True, success=True, extracted_content='Completed.')),
		]
	)

	assert history.policy_violations() == []
	assert history.ambiguous_policy_transitions() == [transition]
	assert history.policy_enforcement_was_unavailable() is False
	assert history.is_successful() is False
	assert 'could not attribute its cause' in (history.final_result() or '')

	restored = AgentHistoryList.load_from_dict(history.model_dump(), AgentOutput)
	assert restored.policy_violations() == []
	assert restored.ambiguous_policy_transitions() == [transition]
	assert restored.is_successful() is False


async def test_policy_violation_remains_sticky_after_message_compaction(httpserver, policy_browser_session, tmp_path):
	violation, tools = await _evaluate_page(
		httpserver,
		policy_browser_session,
		'<button id="place" disabled>Place</button>',
		"try { document.querySelector('#place').disabled = false; } catch (_) {} 'attempted'",
	)
	assert [item.code for item in violation.policy_violations] == ['disabled_control_bypass']

	manager = MessageManager(
		task='Complete the order form',
		system_message=SystemMessage(content='system prompt'),
		file_system=FileSystem(tmp_path / 'compaction', create_default_files=False),
	)
	manager.state.agent_history_items = [
		HistoryItem(step_number=0, system_message='Agent initialized'),
		HistoryItem(
			step_number=1,
			action_results='Browser Use blocked prohibited evaluate attempt(s): disabled_control_bypass.',
		),
	]
	llm = AsyncMock(spec=BaseChatModel)
	llm.ainvoke.return_value = ChatInvokeCompletion(completion='The page was reviewed.', usage=None)
	compacted = await manager.maybe_compact_messages(
		llm=llm,
		settings=MessageCompactionSettings(compact_every_n_steps=1, trigger_char_count=0, keep_last_items=0),
		step_info=AgentStepInfo(step_number=1, max_steps=5),
	)
	assert compacted is True
	assert manager.state.compacted_memory == 'The page was reviewed.'
	assert len(manager.state.agent_history_items) == 1

	completion = await tools.done(
		text='The order was placed.',
		success=True,
		browser_session=policy_browser_session,
		file_system=FileSystem(tmp_path / 'completion', create_default_files=False),
	)
	assert completion.success is False
	assert 'blocked prohibited evaluate attempt' in (completion.extracted_content or '')


def test_structured_output_contract_is_preserved_after_confirmed_violation():
	marker = ConfirmedPolicyViolation(code='disabled_control_bypass')
	structured_action_model = AgentOutput.type_with_custom_actions(_StructuredDone)
	model_output = AgentOutput.model_construct(action=[_StructuredDone(done={'data': {'answer': 'complete'}, 'success': True})])
	json_result = json.dumps({'answer': 'complete'})
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(policy_violations=[marker])),
			_history_step(ActionResult(is_done=True, success=False, extracted_content=json_result), model_output),
		]
	)
	history._output_model_schema = _Answer

	assert history.final_result() == json_result
	assert history.get_structured_output(_Answer) == _Answer(answer='complete')
	assert history.is_successful() is False
	assert history.policy_violations() == [marker]

	restored = AgentHistoryList.load_from_dict(history.model_dump(), structured_action_model)
	assert restored.final_result() == json_result
	assert restored.get_structured_output(_Answer) == _Answer(answer='complete')
	assert restored.is_successful() is False
