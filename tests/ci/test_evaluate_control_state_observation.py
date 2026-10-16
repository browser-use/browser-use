"""Local browser tests for evaluate control-state observations."""

import asyncio

import pytest
from pydantic import BaseModel

import browser_use.tools.service as tools_service
from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, AgentOutput, BrowserStateHistory
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.tools.service import Tools, _compare_control_state_snapshots


class _StructuredAnswer(BaseModel):
	answer: str


@pytest.fixture(scope='module')
async def observation_browser_session():
	"""Start a local headless browser without optional extension downloads."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
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


async def _evaluate_page(
	httpserver, browser_session: BrowserSession, html: str, code: str, tools: Tools | None = None
) -> ActionResult:
	httpserver.expect_request('/').respond_with_data(html, content_type='text/html')
	tools = tools or Tools()
	await tools.navigate(url=httpserver.url_for('/'), new_tab=False, browser_session=browser_session)
	return await tools.evaluate(code=code, browser_session=browser_session)


async def test_directly_enabling_disabled_control_is_recorded_as_observation(httpserver, observation_browser_session):
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		'<button id="submit" disabled>Submit</button><button id="normal">Normal</button>',
		"document.querySelector('#submit').disabled = false; 'enabled'",
	)

	assert result.extracted_content == 'enabled'
	assert result.control_state_change_observation is not None
	assert result.control_state_change_observation.disabled_to_enabled == 1
	assert result.policy_violation is None


async def test_removing_disabled_attribute_is_recorded_as_observation(httpserver, observation_browser_session):
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		'<button id="submit" disabled>Submit</button>',
		"document.querySelector('#submit').removeAttribute('disabled'); 'enabled'",
	)

	assert result.extracted_content == 'enabled'
	assert result.control_state_change_observation is not None
	assert result.control_state_change_observation.disabled_to_enabled == 1
	assert result.policy_violation is None


async def test_harmless_evaluate_keeps_result_unchanged(httpserver, observation_browser_session):
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		'<button id="submit" disabled>Submit</button><button id="normal">Normal</button>',
		"document.body.insertAdjacentHTML('afterbegin', '<button id=added>Added</button>'); document.title",
	)

	assert result.extracted_content == ''
	assert result.control_state_change_observation is None
	assert result.policy_violation is None


async def test_snapshot_uses_an_execution_world_isolated_from_page_globals(httpserver, observation_browser_session):
	html = """<!doctype html>
<button id="submit" disabled>Submit</button>
<script>
Object.defineProperty(globalThis, '__browser_use_control_state_ids__', {
  value: {ids: {get() { throw new Error('page world was reused'); }}, nextId: 0}
});
</script>"""
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		html,
		"document.querySelector('#submit').disabled = false; 'enabled'",
	)

	assert result.extracted_content == 'enabled'
	assert result.control_state_change_observation is not None
	assert result.control_state_change_observation.disabled_to_enabled == 1


async def test_page_owned_synchronous_handler_is_observed_but_not_confirmed(httpserver, observation_browser_session):
	html = """<!doctype html>
<input id="name"><button id="submit" disabled>Submit</button>
<script>
document.querySelector('#name').addEventListener('input', () => {
  document.querySelector('#submit').disabled = false;
});
</script>"""
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		html,
		"(() => { const input = document.querySelector('#name'); input.value = 'local'; input.dispatchEvent(new Event('input', {bubbles: true})); return 'typed'; })()",
	)

	assert result.extracted_content == 'typed'
	assert result.control_state_change_observation is not None
	assert result.control_state_change_observation.disabled_to_enabled == 1
	assert result.policy_violation is None


async def test_delayed_page_handler_after_evaluate_expression_is_observed(httpserver, observation_browser_session):
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		'<button id="submit" disabled>Submit</button>',
		"setTimeout(() => { document.querySelector('#submit').disabled = false; }, 1000); 'scheduled'",
	)

	assert result.extracted_content == 'scheduled'
	assert result.control_state_change_observation is None
	assert result.policy_violation is None
	await asyncio.sleep(1.1)
	delayed_state = await observation_browser_session.cdp_client.send.Runtime.evaluate(
		params={'expression': "document.querySelector('#submit').disabled", 'returnByValue': True},
		session_id=(await observation_browser_session.get_or_create_cdp_session()).session_id,
	)
	assert delayed_state['result']['value'] is False


async def test_readonly_to_editable_change_is_observed(httpserver, observation_browser_session):
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		'<input id="locked" readonly value="local">',
		"document.querySelector('#locked').removeAttribute('readonly'); 'editable'",
	)

	assert result.extracted_content == 'editable'
	assert result.control_state_change_observation is not None
	assert result.control_state_change_observation.readonly_to_editable == 1
	assert result.policy_violation is None


async def test_duplicate_ids_do_not_match_a_removed_control_to_its_sibling(httpserver, observation_browser_session):
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		'<button id="duplicate" disabled>Locked</button><button id="duplicate">Available</button>',
		"document.querySelector('#duplicate').remove(); 'removed'",
	)

	assert result.control_state_change_observation is not None
	assert result.control_state_change_observation.disabled_to_enabled == 0
	assert result.control_state_change_observation.restricted_controls_unmatched == 1
	assert result.policy_violation is None


async def test_removed_disabled_control_is_unmatched(httpserver, observation_browser_session):
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		'<button id="submit" disabled>Submit</button>',
		"document.querySelector('#submit').remove(); 'removed'",
	)

	assert result.control_state_change_observation is not None
	assert result.control_state_change_observation.disabled_to_enabled == 0
	assert result.control_state_change_observation.restricted_controls_unmatched == 1


async def test_replacement_with_same_id_is_unmatched(httpserver, observation_browser_session):
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		'<button id="submit" disabled>Submit</button>',
		"const old = document.querySelector('#submit'); old.replaceWith(Object.assign(document.createElement('button'), {id: old.id, textContent: 'Submit'})); 'replaced'",
	)

	assert result.control_state_change_observation is not None
	assert result.control_state_change_observation.disabled_to_enabled == 0
	assert result.control_state_change_observation.restricted_controls_unmatched == 1


async def test_moving_same_control_preserves_identity(httpserver, observation_browser_session):
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		'<div id="first"><button id="submit" disabled>Submit</button></div><div id="second"></div>',
		"document.querySelector('#second').append(document.querySelector('#submit')); 'moved'",
	)

	assert result.control_state_change_observation is None
	assert result.policy_violation is None


async def test_observation_survives_done_and_structured_json_remains_parseable(httpserver, observation_browser_session):
	result = await _evaluate_page(
		httpserver,
		observation_browser_session,
		'<button id="submit" disabled>Submit</button>',
		'document.querySelector(\'#submit\').disabled = false; \'{"answer":"complete"}\'',
	)
	done_result = ActionResult(is_done=True, success=True, extracted_content='{"answer":"complete"}')
	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=None,
				result=[result],
				state=BrowserStateHistory(url=httpserver.url_for('/'), title='Local fixture', tabs=[], interacted_element=[]),
			),
			AgentHistory(
				model_output=None,
				result=[done_result],
				state=BrowserStateHistory(url=httpserver.url_for('/'), title='Local fixture', tabs=[], interacted_element=[]),
			),
		]
	)
	history._output_model_schema = _StructuredAnswer

	assert history.is_successful() is True
	assert history.final_result() == '{"answer":"complete"}'
	assert history.structured_output == _StructuredAnswer(answer='complete')
	assert len(history.control_state_change_observations()) == 1
	assert result.policy_violation is None

	restored = AgentHistoryList.load_from_dict(history.model_dump(), AgentOutput)
	assert restored.control_state_change_observations() == history.control_state_change_observations()
	assert restored.is_successful() is True
	assert restored.get_structured_output(_StructuredAnswer) == _StructuredAnswer(answer='complete')
	assert restored.final_result() == (
		'{"answer":"complete"}\n\n'
		'Observed around evaluate: disabled/read-only form-control state changed or a restricted control could not be '
		'matched between snapshots. This observation does not identify its cause.'
	)


def _snapshot(*controls: dict[str, object], context_id: int = 1) -> dict[str, object]:
	return {'context_identity': ('frame-1', 'loader-1', context_id), 'controls': list(controls)}


def test_duplicate_dom_ids_do_not_create_control_identity():
	before = _snapshot(
		{'key': 'node-1', 'dom_id': 'duplicate', 'disabled': True, 'readonly': False},
		{'key': 'node-2', 'dom_id': 'duplicate', 'disabled': False, 'readonly': False},
	)
	after = _snapshot({'key': 'node-2', 'dom_id': 'duplicate', 'disabled': False, 'readonly': False})

	observation = _compare_control_state_snapshots(before, after)

	assert observation is not None
	assert observation.disabled_to_enabled == 0
	assert observation.restricted_controls_unmatched == 1


def test_duplicate_snapshot_node_keys_are_unmatched_not_compared():
	observation = _compare_control_state_snapshots(
		_snapshot(
			{'key': 'ambiguous-node', 'disabled': True, 'readonly': False},
			{'key': 'ambiguous-node', 'disabled': False, 'readonly': False},
		),
		_snapshot({'key': 'ambiguous-node', 'disabled': False, 'readonly': False}),
	)

	assert observation is not None
	assert observation.disabled_to_enabled == 0
	assert observation.restricted_controls_unmatched == 1


def test_removed_restricted_control_is_reported_as_unmatched_not_transition():
	observation = _compare_control_state_snapshots(
		_snapshot({'key': 'node-1', 'disabled': True, 'readonly': False}),
		_snapshot(),
	)

	assert observation is not None
	assert observation.disabled_to_enabled == 0
	assert observation.restricted_controls_unmatched == 1


def test_added_restricted_control_is_reported_as_unmatched():
	observation = _compare_control_state_snapshots(
		_snapshot(),
		_snapshot({'key': 'new-node', 'disabled': True, 'readonly': False}),
	)

	assert observation is not None
	assert observation.disabled_to_enabled == 0
	assert observation.restricted_controls_unmatched == 1


def test_replacement_control_with_same_dom_id_is_unmatched():
	observation = _compare_control_state_snapshots(
		_snapshot({'key': 'old-node', 'dom_id': 'submit', 'disabled': True, 'readonly': False}),
		_snapshot({'key': 'new-node', 'dom_id': 'submit', 'disabled': False, 'readonly': False}),
	)

	assert observation is not None
	assert observation.disabled_to_enabled == 0
	assert observation.restricted_controls_unmatched == 1


def test_dom_movement_does_not_change_identity_or_report_transition():
	before = _snapshot(
		{'key': 'node-1', 'dom_position': 0, 'disabled': True, 'readonly': False},
		{'key': 'node-2', 'dom_position': 1, 'disabled': False, 'readonly': False},
	)
	after = _snapshot(
		{'key': 'node-2', 'dom_position': 0, 'disabled': False, 'readonly': False},
		{'key': 'node-1', 'dom_position': 1, 'disabled': True, 'readonly': False},
	)

	assert _compare_control_state_snapshots(before, after) is None


def test_different_document_contexts_are_reported_as_unmatched():
	before = _snapshot({'key': 'node-1', 'disabled': True, 'readonly': False}, context_id=1)
	after = _snapshot({'key': 'node-1', 'disabled': False, 'readonly': False}, context_id=2)

	observation = _compare_control_state_snapshots(before, after)

	assert observation is not None
	assert observation.disabled_to_enabled == 0
	assert observation.restricted_controls_unmatched == 1


async def test_cold_and_warm_snapshots_fit_budget_for_representative_dom(httpserver, observation_browser_session):
	control_count = 1000
	html = '<button disabled>locked</button>' * control_count
	httpserver.expect_request('/many-controls').respond_with_data(html, content_type='text/html')
	tools = Tools()
	await tools.navigate(url=httpserver.url_for('/many-controls'), new_tab=False, browser_session=observation_browser_session)
	cdp_session = await observation_browser_session.get_or_create_cdp_session()

	cold = await tools._snapshot_evaluate_control_state(cdp_session)
	warm = await tools._snapshot_evaluate_control_state(cdp_session)

	assert cold is not None
	assert warm is not None
	assert len(cold['controls']) == control_count
	assert len(warm['controls']) == control_count
	assert cold['context_identity'] == warm['context_identity']


async def test_registered_evaluate_keeps_result_when_real_cdp_snapshots_timeout(
	monkeypatch, httpserver, observation_browser_session
):
	monkeypatch.setattr(tools_service, '_EVALUATE_CONTROL_STATE_SNAPSHOT_TIMEOUT_SECONDS', 0.00001)
	tools = Tools()
	original_snapshot = tools._snapshot_evaluate_control_state
	snapshot_results = []

	async def record_snapshot(cdp_session):
		result = await original_snapshot(cdp_session)
		snapshot_results.append(result)
		return result

	monkeypatch.setattr(tools, '_snapshot_evaluate_control_state', record_snapshot)
	result = await _evaluate_page(
		httpserver, observation_browser_session, '<button disabled>Submit</button>', '40 + 2', tools=tools
	)

	assert result.extracted_content == '42'
	assert result.error is None
	assert result.policy_violation is None
	assert result.control_state_change_observation is None
	assert snapshot_results == [None]


async def test_registered_evaluate_keeps_result_when_after_snapshot_times_out(
	monkeypatch, httpserver, observation_browser_session
):
	tools = Tools()
	original_snapshot = tools._snapshot_evaluate_control_state
	snapshot_results = []

	async def record_snapshot(cdp_session):
		result = await original_snapshot(cdp_session)
		snapshot_results.append(result)
		if len(snapshot_results) == 1:
			monkeypatch.setattr(tools_service, '_EVALUATE_CONTROL_STATE_SNAPSHOT_TIMEOUT_SECONDS', 0.00001)
		return result

	monkeypatch.setattr(tools, '_snapshot_evaluate_control_state', record_snapshot)
	result = await _evaluate_page(
		httpserver, observation_browser_session, '<button disabled>Submit</button>', '40 + 2', tools=tools
	)

	assert snapshot_results[0] is not None
	assert snapshot_results[1] is None
	assert result.extracted_content == '42'
	assert result.error is None
	assert result.policy_violation is None
	assert result.control_state_change_observation is None


async def test_registered_evaluate_keeps_javascript_error_when_real_cdp_snapshots_timeout(
	monkeypatch, httpserver, observation_browser_session
):
	code = "throw new Error('expected evaluate error')"
	httpserver.expect_request('/').respond_with_data('<button disabled>Submit</button>', content_type='text/html')
	tools = Tools()
	await tools.navigate(url=httpserver.url_for('/'), new_tab=False, browser_session=observation_browser_session)
	cdp_session = await observation_browser_session.get_or_create_cdp_session()
	baseline = await tools._execute_evaluate_javascript(code, cdp_session)
	monkeypatch.setattr(tools_service, '_EVALUATE_CONTROL_STATE_SNAPSHOT_TIMEOUT_SECONDS', 0.00001)
	result = await tools.evaluate(code=code, browser_session=observation_browser_session)

	assert result.extracted_content is None
	assert result.error == baseline.error
	assert result.control_state_change_observation is None
	assert result.policy_violation is None


async def test_snapshot_overhead_does_not_shorten_real_evaluate_action_timeout(httpserver, observation_browser_session):
	tools = Tools()
	httpserver.expect_request('/deadline').respond_with_data('<button disabled>Submit</button>', content_type='text/html')
	await tools.navigate(url=httpserver.url_for('/deadline'), new_tab=False, browser_session=observation_browser_session)
	action_model = tools.registry.create_action_model(include_actions=['evaluate']).model_validate(
		{'evaluate': {'code': "new Promise(resolve => setTimeout(() => resolve('completed'), 150))"}}
	)
	start = asyncio.get_running_loop().time()

	result = await tools.act(
		action=action_model,
		browser_session=observation_browser_session,
		action_timeout=0.1,
	)

	assert result.extracted_content == 'completed'
	assert result.error is None
	assert asyncio.get_running_loop().time() - start > 0.1


async def test_real_cdp_cancellation_removes_pending_request(httpserver, observation_browser_session, monkeypatch):
	await _evaluate_page(httpserver, observation_browser_session, '<button>Ready</button>', 'document.title')
	cdp_session = await observation_browser_session.get_or_create_cdp_session()
	cdp_client = cdp_session.cdp_client
	promise_duration_ms = 5_000
	expression = f"new Promise(resolve => setTimeout(() => resolve('late response'), {promise_duration_ms}))"
	request_id = None
	original_send_raw = cdp_client.send_raw

	async def track_send_raw(method, params=None, session_id=None):
		nonlocal request_id
		if method == 'Runtime.evaluate' and params and params.get('expression') == expression:
			request_id = cdp_client.msg_id + 1
		return await original_send_raw(method=method, params=params, session_id=session_id)

	monkeypatch.setattr(cdp_client, 'send_raw', track_send_raw)
	task = asyncio.create_task(
		cdp_client.send.Runtime.evaluate(
			params={'expression': expression, 'returnByValue': True, 'awaitPromise': True},
			session_id=cdp_session.session_id,
		)
	)
	try:
		loop = asyncio.get_running_loop()
		pending_request_deadline = loop.time() + 2.0
		while request_id is None or request_id not in cdp_client.pending_requests:
			remaining = pending_request_deadline - loop.time()
			if remaining <= 0:
				pytest.fail('Timed out waiting for the tracked CDP Runtime.evaluate request to become pending')
			await asyncio.sleep(min(0.01, remaining))

		assert not task.done()
		task.cancel()
		with pytest.raises(asyncio.CancelledError):
			await task
		assert request_id not in cdp_client.pending_requests
		await asyncio.sleep(promise_duration_ms / 1_000 + 0.1)
		assert request_id not in cdp_client.pending_requests
	finally:
		if not task.done():
			task.cancel()
			await asyncio.gather(task, return_exceptions=True)
