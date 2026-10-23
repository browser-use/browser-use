import json

import pytest
from pydantic import BaseModel, RootModel, ValidationError

from browser_use import ConfirmedPolicyViolation as PublicConfirmedPolicyViolation
from browser_use.agent.views import (
	ActionResult,
	AgentHistory,
	AgentHistoryList,
	AgentOutput,
	BrowserStateHistory,
	ConfirmedPolicyViolation,
	ControlStateChangeObservation,
)
from browser_use.tools.registry.views import ActionModel


class StructuredAnswer(BaseModel):
	answer: str


class StructuredAnswers(RootModel[list[str]]):
	pass


class StructuredCount(RootModel[int]):
	pass


class ProbeAction(ActionModel):
	probe: dict[str, str]


def _history_step(*results: ActionResult) -> AgentHistory:
	return AgentHistory(
		model_output=None,
		result=list(results),
		state=BrowserStateHistory(url='http://localhost/', title='Local fixture', tabs=[], interacted_element=[]),
	)


def _confirmed_violation() -> ConfirmedPolicyViolation:
	return ConfirmedPolicyViolation(code='disabled_control_bypass')


def test_confirmed_violation_survives_successful_done_result() -> None:
	violation = _confirmed_violation()
	assert isinstance(violation, PublicConfirmedPolicyViolation)
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(policy_violation=violation)),
			_history_step(ActionResult(is_done=True, success=True, extracted_content='The task is complete.')),
		]
	)

	assert history.is_done() is True
	assert history.is_successful() is False
	assert history.policy_violations() == [violation]
	assert history.final_result() == (
		'The task is complete.\n\nConfirmed policy violation: the agent attempted to bypass a disabled or read-only form control.'
	)
	assert history.action_history()[0] == [{'policy_violation': {'code': 'disabled_control_bypass'}}]


def test_compact_action_history_keeps_marker_with_its_action() -> None:
	marker = _confirmed_violation()
	model_output = AgentOutput.model_construct(action=[ProbeAction(probe={'target': 'form'})])
	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=model_output,
				result=[ActionResult(policy_violation=marker)],
				state=BrowserStateHistory(url='http://localhost/', title='Local fixture', tabs=[], interacted_element=[]),
			)
		]
	)

	assert history.action_history()[0][0]['policy_violation'] == {'code': 'disabled_control_bypass'}


def test_structured_output_stays_parseable_and_exposes_violation_accessor() -> None:
	json_result = '{"answer":"complete"}'
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(policy_violation=_confirmed_violation())),
			_history_step(ActionResult(is_done=True, success=True, extracted_content=json_result)),
		]
	)
	history._output_model_schema = StructuredAnswer

	assert history.final_result() == json_result
	assert json.loads(history.final_result() or '') == {'answer': 'complete'}
	assert history.structured_output == StructuredAnswer(answer='complete')
	assert [item.code for item in history.policy_violations()] == ['disabled_control_bypass']

	# The marker also survives the serialized history path used by sandbox callers.
	restored = AgentHistoryList.load_from_dict(history.model_dump(), AgentOutput)
	assert restored.final_result() == (
		f'{json_result}\n\nConfirmed policy violation: the agent attempted to bypass a disabled or read-only form control.'
	)
	assert restored.get_structured_output(StructuredAnswer) == StructuredAnswer(answer='complete')
	assert [item.code for item in restored.policy_violations()] == ['disabled_control_bypass']


@pytest.mark.parametrize(
	('output_model', 'json_result'),
	[
		pytest.param(StructuredAnswer, '{"answer":"complete"}', id='object'),
		pytest.param(StructuredAnswers, '["first","second"]', id='array'),
		pytest.param(StructuredCount, '2', id='scalar'),
	],
)
def test_schema_backed_json_values_remain_unchanged_with_observation(output_model, json_result: str) -> None:
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(control_state_change_observation=ControlStateChangeObservation(disabled_to_enabled=1))),
			_history_step(ActionResult(is_done=True, success=True, extracted_content=json_result)),
		]
	)
	history._output_model_schema = output_model

	assert history.final_result() == json_result
	assert history.structured_output == output_model.model_validate_json(json_result)
	assert len(history.control_state_change_observations()) == 1


def test_normal_success_without_marker_is_unchanged() -> None:
	history = AgentHistoryList(
		history=[_history_step(ActionResult(is_done=True, success=True, extracted_content='Completed normally.'))]
	)

	assert history.is_successful() is True
	assert history.final_result() == 'Completed normally.'
	assert history.policy_violations() == []
	assert history.action_history() == [[]]


def test_empty_history_preserves_existing_defaults() -> None:
	history = AgentHistoryList(history=[])

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.is_successful() is None
	assert history.action_history() == []


def test_step_without_final_result_preserves_existing_defaults() -> None:
	history = AgentHistoryList(history=[_history_step()])

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.is_successful() is None
	assert history.action_history() == [[]]


def test_multiple_markers_are_preserved_with_one_disclosure() -> None:
	history = AgentHistoryList(
		history=[
			_history_step(
				ActionResult(policy_violation=_confirmed_violation()), ActionResult(policy_violation=_confirmed_violation())
			),
			_history_step(ActionResult(is_done=True, success=True, extracted_content='Completed with a violation.')),
		]
	)

	assert len(history.policy_violations()) == 2
	assert history.is_successful() is False
	assert history.final_result() == (
		'Completed with a violation.\n\n'
		'Confirmed policy violation: the agent attempted to bypass a disabled or read-only form control.'
	)
	assert history.action_history()[0] == [
		{'policy_violation': {'code': 'disabled_control_bypass'}},
		{'policy_violation': {'code': 'disabled_control_bypass'}},
	]


def test_errors_metadata_and_untrusted_text_do_not_trigger_violation() -> None:
	warning = 'The page displayed a warning about a possible policy violation.'
	history = AgentHistoryList(
		history=[
			_history_step(
				ActionResult(
					error='A normal action error',
					long_term_memory='Warning: possible disabled-control bypass.',
					metadata={'policy_violation': {'code': 'disabled_control_bypass'}},
				)
			),
			_history_step(
				ActionResult(
					is_done=True,
					success=True,
					extracted_content=warning,
					metadata={'confirmed_policy_violation': True},
				)
			),
		]
	)

	assert history.has_errors() is True
	assert history.is_successful() is True
	assert history.final_result() == warning
	assert history.policy_violations() == []

	with pytest.raises(ValidationError):
		ConfirmedPolicyViolation(code='warning')  # type: ignore[arg-type]


def test_policy_marker_is_immutable() -> None:
	marker = _confirmed_violation()
	with pytest.raises(ValidationError):
		setattr(marker, 'code', 'warning')


@pytest.mark.parametrize(
	'invalid_marker',
	[
		pytest.param(ConfirmedPolicyViolation.model_construct(), id='missing-code'),
		pytest.param(ConfirmedPolicyViolation.model_construct(code='unexpected'), id='unexpected-code'),
	],
)
def test_invalid_model_construct_markers_are_ignored(invalid_marker: ConfirmedPolicyViolation) -> None:
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(policy_violation=invalid_marker)),
			_history_step(ActionResult(is_done=True, success=True, extracted_content='Completed normally.')),
		]
	)

	assert history.policy_violations() == []
	assert history.is_successful() is True
	assert history.final_result() == 'Completed normally.'
	assert history.action_history() == [[], []]


def test_malformed_serialized_marker_is_rejected() -> None:
	serialized_history = {
		'history': [
			{
				'model_output': None,
				'result': [{'policy_violation': {'code': 'warning'}}],
				'state': {'url': 'http://localhost/', 'title': 'Local fixture', 'tabs': [], 'interacted_element': []},
			}
		]
	}

	with pytest.raises(ValidationError):
		AgentHistoryList.load_from_dict(serialized_history, AgentOutput)


@pytest.mark.parametrize(
	'json_result',
	[
		pytest.param('{"answer":"complete"}', id='object'),
		pytest.param('["first","second"]', id='array'),
		pytest.param('2', id='number-scalar'),
		pytest.param('"complete"', id='string-scalar'),
		pytest.param('true', id='boolean-scalar'),
		pytest.param('null', id='null-scalar'),
	],
)
def test_json_shaped_text_without_schema_is_disclosed_as_ordinary_text(json_result: str) -> None:
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(policy_violation=_confirmed_violation())),
			_history_step(ActionResult(is_done=True, success=True, extracted_content=json_result)),
		]
	)

	final_result = history.final_result()
	assert final_result == (
		f'{json_result}\n\nConfirmed policy violation: the agent attempted to bypass a disabled or read-only form control.'
	)
	with pytest.raises(json.JSONDecodeError):
		json.loads(final_result or '')
	assert len(history.policy_violations()) == 1


def test_malformed_schema_backed_json_is_not_modified_by_disclosure() -> None:
	malformed_json = '{"answer":'
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(policy_violation=_confirmed_violation())),
			_history_step(ActionResult(is_done=True, success=True, extracted_content=malformed_json)),
		]
	)
	history._output_model_schema = StructuredAnswer

	assert history.final_result() == malformed_json
	with pytest.raises(ValidationError):
		_ = history.structured_output
	assert len(history.policy_violations()) == 1


def test_control_state_observation_survives_later_done_and_is_disclosed_for_text() -> None:
	observation = ControlStateChangeObservation(disabled_to_enabled=1)
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(control_state_change_observation=observation)),
			_history_step(ActionResult(is_done=True, success=True, extracted_content='The task is complete.')),
		]
	)

	assert history.is_successful() is True
	assert history.control_state_change_observations() == [observation]
	assert history.final_result() == (
		'The task is complete.\n\n'
		'Observed around evaluate: disabled/read-only form-control state changed or a restricted control could not be '
		'matched between snapshots. This observation does not identify its cause.'
	)
	assert history.action_history()[0] == [
		{
			'control_state_change_observation': {
				'disabled_to_enabled': 1,
				'readonly_to_editable': 0,
				'restricted_controls_unmatched': 0,
			}
		}
	]


def test_control_state_observation_does_not_break_structured_json() -> None:
	json_result = '{"answer":"complete"}'
	history = AgentHistoryList(
		history=[
			_history_step(ActionResult(control_state_change_observation=ControlStateChangeObservation(disabled_to_enabled=1))),
			_history_step(ActionResult(is_done=True, success=True, extracted_content=json_result)),
		]
	)
	history._output_model_schema = StructuredAnswer

	assert history.final_result() == json_result
	assert json.loads(history.final_result() or '') == {'answer': 'complete'}
	assert history.is_successful() is True
	assert len(history.control_state_change_observations()) == 1
