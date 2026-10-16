"""Local browser tests for evaluate control-state observations."""

import asyncio
from types import SimpleNamespace

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


async def _evaluate_page(httpserver, browser_session: BrowserSession, html: str, code: str) -> ActionResult:
	httpserver.expect_request('/').respond_with_data(html, content_type='text/html')
	tools = Tools()
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
	assert restored.final_result() == history.final_result()


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


class _FakeRuntime:
	def __init__(self, *, failure_at: int | None = None, timeout_at: int | None = None, js_delay: float = 0, js_result=None):
		self.failure_at = failure_at
		self.timeout_at = timeout_at
		self.js_delay = js_delay
		self.js_result = js_result or {'result': {'type': 'string', 'value': 'original-return'}}
		self.snapshot_calls = 0
		self.executed_expressions: list[str] = []

	async def evaluate(self, *, params: dict, session_id: str):
		expression = params['expression']
		self.executed_expressions.append(expression)
		if expression == tools_service._CONTROL_STATE_SNAPSHOT_SCRIPT:
			self.snapshot_calls += 1
			if self.failure_at == self.snapshot_calls:
				raise RuntimeError('synthetic snapshot failure')
			if self.timeout_at == self.snapshot_calls:
				await asyncio.sleep(1)
			return {
				'result': {
					'value': {'controls': [{'key': 'node-1', 'disabled': True, 'readonly': False}]},
				}
			}
		if self.js_delay:
			await asyncio.sleep(self.js_delay)
		return self.js_result


class _FakeCDPClient:
	def __init__(self, runtime: _FakeRuntime):
		self.send = SimpleNamespace(
			Page=SimpleNamespace(
				getFrameTree=self.get_frame_tree,
				createIsolatedWorld=self.create_isolated_world,
			),
			Runtime=runtime,
		)

	async def get_frame_tree(self, *, session_id: str):
		return {'frameTree': {'frame': {'id': 'frame-1', 'loaderId': 'loader-1'}}}

	async def create_isolated_world(self, *, params: dict, session_id: str):
		return {'executionContextId': 10}


class _FakeBrowserSession:
	def __init__(self, runtime: _FakeRuntime):
		self.cdp_client = _FakeCDPClient(runtime)
		self.cdp_session = SimpleNamespace(cdp_client=self.cdp_client, session_id='session-1')

	async def get_or_create_cdp_session(self):
		return self.cdp_session

	async def get_current_page_url(self):
		return 'http://localhost/'


@pytest.mark.parametrize('failure_at', [1, 2], ids=['before-snapshot', 'after-snapshot'])
async def test_registered_evaluate_ignores_snapshot_failures(failure_at: int):
	runtime = _FakeRuntime(failure_at=failure_at)
	tools = Tools()

	result = await tools.evaluate(code='40 + 2', browser_session=_FakeBrowserSession(runtime))

	assert result.extracted_content == 'original-return'
	assert result.error is None
	assert result.policy_violation is None
	assert result.control_state_change_observation is None
	assert '40 + 2' in runtime.executed_expressions


async def test_registered_harmless_evaluate_takes_only_bounded_snapshots():
	runtime = _FakeRuntime()
	tools = Tools()
	result = await tools.evaluate(code='40 + 2', browser_session=_FakeBrowserSession(runtime))

	assert result.extracted_content == 'original-return'
	assert result.control_state_change_observation is None
	assert runtime.snapshot_calls == 2


async def test_snapshot_overhead_does_not_shorten_evaluate_action_timeout():
	runtime = _FakeRuntime(js_delay=0.1)
	tools = Tools()
	action_model = tools.registry.create_action_model(include_actions=['evaluate']).model_validate(
		{'evaluate': {'code': '40 + 2'}}
	)
	start = asyncio.get_running_loop().time()

	result = await tools.act(
		action=action_model,
		browser_session=_FakeBrowserSession(runtime),  # type: ignore[arg-type]
		action_timeout=0.05,
	)

	assert result.extracted_content == 'original-return'
	assert result.error is None
	assert asyncio.get_running_loop().time() - start > 0.05


async def test_registered_evaluate_keeps_javascript_error_when_snapshot_fails():
	runtime = _FakeRuntime(
		failure_at=2,
		js_result={'exceptionDetails': {'text': 'ReferenceError: missing is not defined'}},
	)
	tools = Tools()

	result = await tools.evaluate(code='missing', browser_session=_FakeBrowserSession(runtime))

	assert result.extracted_content is None
	assert result.error is not None
	assert 'JavaScript execution error: ReferenceError: missing is not defined' in result.error
	assert result.control_state_change_observation is None
	assert result.policy_violation is None


@pytest.mark.parametrize('timeout_at', [1, 2], ids=['before-snapshot', 'after-snapshot'])
async def test_registered_evaluate_snapshot_timeout_keeps_javascript_result(monkeypatch, timeout_at: int):
	monkeypatch.setattr(tools_service, '_EVALUATE_CONTROL_STATE_SNAPSHOT_TIMEOUT_SECONDS', 0.01)
	runtime = _FakeRuntime(timeout_at=timeout_at)
	tools = Tools()
	start = asyncio.get_running_loop().time()

	result = await tools.evaluate(code='40 + 2', browser_session=_FakeBrowserSession(runtime))

	assert result.extracted_content == 'original-return'
	assert result.error is None
	assert result.control_state_change_observation is None
	assert result.policy_violation is None
	assert asyncio.get_running_loop().time() - start < 0.2
	assert '40 + 2' in runtime.executed_expressions


async def test_snapshot_timeout_is_bounded_and_optional(monkeypatch):
	monkeypatch.setattr(tools_service, '_EVALUATE_CONTROL_STATE_SNAPSHOT_TIMEOUT_SECONDS', 0.01)
	start = asyncio.get_running_loop().time()

	runtime = _FakeRuntime(timeout_at=1)
	cdp_session = await _FakeBrowserSession(runtime).get_or_create_cdp_session()
	result = await Tools()._snapshot_evaluate_control_state(cdp_session)

	assert result is None
	assert asyncio.get_running_loop().time() - start < 0.2
