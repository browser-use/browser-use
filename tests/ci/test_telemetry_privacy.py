"""Check outgoing telemetry with local fakes only. No analytics requests are made."""

import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from browser_use import Agent
from browser_use.telemetry import ProductTelemetry
from browser_use.telemetry.views import (
	AgentTelemetryEvent,
	BaseTelemetryEvent,
	MCPClientTelemetryEvent,
	MCPServerTelemetryEvent,
)

PRIVATE = 'PRIVATE_TASK_CONTENT_DO_NOT_SEND'


def agent_event() -> AgentTelemetryEvent:
	return AgentTelemetryEvent(
		task=f'Process customer document {PRIVATE}',
		model='test-model',
		model_provider='test-provider',
		max_steps=10,
		max_actions_per_step=3,
		use_vision=False,
		version='test-version',
		source='pip',
		cdp_url=f'https://internal.example/{PRIVATE}',
		agent_type=None,
		action_errors=[f'Could not enter {PRIVATE}'],
		action_history=[[{'input': {'text': PRIVATE}}]],
		urls_visited=[f'https://internal.example/?customer={PRIVATE}'],
		steps=2,
		total_input_tokens=100,
		total_output_tokens=20,
		prompt_cached_tokens=30,
		total_tokens=120,
		total_duration_seconds=1.5,
		success=False,
		final_result_response=PRIVATE,
		error_message=PRIVATE,
		judge_verdict=False,
		judge_reasoning=PRIVATE,
		judge_failure_reason=PRIVATE,
		judge_reached_captcha=False,
		judge_impossible_task=False,
	)


@pytest.fixture
def make_telemetry(monkeypatch):
	# Obtain the class behind the existing singleton without initializing a
	# real analytics client, then construct isolated instances for these tests.
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
	telemetry_class = type(ProductTelemetry())
	sink = Mock()
	constructor = Mock(return_value=sink)
	monkeypatch.setattr('posthog.Posthog', constructor)
	monkeypatch.setattr('browser_use.telemetry.service.get_or_create_device_id', lambda: 'synthetic-device')

	def create(enabled=True):
		monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'true' if enabled else 'false')
		return telemetry_class(), sink, constructor

	return create


def test_agent_payload_contains_only_operational_metrics(make_telemetry):
	telemetry, sink, _ = make_telemetry()
	event = agent_event()
	telemetry.capture(event)

	sink.capture.assert_called_once()
	payload = sink.capture.call_args.kwargs
	assert PRIVATE not in json.dumps(payload)
	assert payload['event'] == 'agent_event'
	assert payload['distinct_id'] == 'synthetic-device'
	assert payload['properties'] == {
		'model': 'test-model',
		'model_provider': 'test-provider',
		'max_steps': 10,
		'max_actions_per_step': 3,
		'use_vision': False,
		'version': 'test-version',
		'source': 'pip',
		'agent_type': None,
		'steps': 2,
		'total_input_tokens': 100,
		'total_output_tokens': 20,
		'prompt_cached_tokens': 30,
		'total_tokens': 120,
		'total_duration_seconds': 1.5,
		'success': False,
		'judge_verdict': False,
		'judge_reached_captcha': False,
		'judge_impossible_task': False,
		'is_docker': event.properties['is_docker'],
		'process_person_profile': True,
	}


def test_new_event_fields_are_not_automatically_uploaded():
	@dataclass
	class ExtendedAgentEvent(AgentTelemetryEvent):
		future_task_field: str = PRIVATE

	event = ExtendedAgentEvent(**vars(agent_event()))
	assert 'future_task_field' not in event.properties
	assert PRIVATE not in json.dumps(event.properties)


def test_unknown_event_has_no_implicitly_allowed_content():
	@dataclass
	class UnreviewedEvent(BaseTelemetryEvent):
		content: str = PRIVATE
		name: str = 'unreviewed'

	assert set(UnreviewedEvent().properties) == {'is_docker'}


@pytest.mark.parametrize(
	'event',
	[
		MCPClientTelemetryEvent(
			server_name=PRIVATE,
			command=f'python agent.py --task {PRIVATE}',
			tools_discovered=4,
			version='test-version',
			action='tool_call',
			tool_name=PRIVATE,
			duration_seconds=0.5,
			error_message=PRIVATE,
		),
		MCPServerTelemetryEvent(
			version='test-version',
			action='tool_call',
			tool_name=PRIVATE,
			duration_seconds=0.5,
			error_message=PRIVATE,
			parent_process_cmdline=f'agent --prompt {PRIVATE}',
		),
	],
)
def test_mcp_telemetry_excludes_commands_and_free_text(make_telemetry, event):
	telemetry, sink, _ = make_telemetry()
	telemetry.capture(event)
	properties = sink.capture.call_args.kwargs['properties']
	assert PRIVATE not in json.dumps(sink.capture.call_args.kwargs)
	assert properties['action'] == 'tool_call'
	assert properties['duration_seconds'] == 0.5
	assert properties['version'] == 'test-version'


def test_opt_out_does_not_create_client_or_send_events(make_telemetry):
	telemetry, sink, constructor = make_telemetry(enabled=False)
	telemetry.capture(agent_event())
	telemetry._direct_capture(agent_event())
	telemetry.flush()
	constructor.assert_not_called()
	sink.capture.assert_not_called()
	sink.flush.assert_not_called()


def test_automatic_exception_capture_is_disabled(make_telemetry):
	_, _, constructor = make_telemetry()
	assert constructor.call_args.kwargs['enable_exception_autocapture'] is False


@pytest.mark.parametrize('failed', [False, True])
def test_agent_does_not_collect_private_history_for_telemetry(make_telemetry, failed):
	telemetry, sink, _ = make_telemetry()
	history = Mock()
	history.judgement.return_value = {
		'verdict': not failed,
		'reasoning': PRIVATE,
		'failure_reason': PRIVATE,
		'reached_captcha': False,
		'impossible_task': False,
	}
	history.total_duration_seconds.return_value = 1.5
	history.is_successful.return_value = not failed
	# Reading these values at all for telemetry is a regression, even if an
	# eventual serializer would remove them.
	history.final_result.side_effect = AssertionError('Do not collect the final response')
	history.errors.side_effect = AssertionError('Do not collect error text')
	history.urls.side_effect = AssertionError('Do not collect browser URLs')
	history.history = None
	token_cost = Mock()
	token_cost.get_usage_tokens_for_model.return_value = SimpleNamespace(
		prompt_tokens=100, completion_tokens=20, prompt_cached_tokens=30, total_tokens=120
	)
	agent = SimpleNamespace(
		task=PRIVATE,
		llm=SimpleNamespace(model='test-model', provider='test-provider'),
		token_cost_service=token_cost,
		history=history,
		telemetry=telemetry,
		settings=SimpleNamespace(max_actions_per_step=3, use_vision=False),
		version='test-version',
		source='pip',
		state=SimpleNamespace(n_steps=2),
	)
	Agent._log_agent_event(agent, max_steps=10, agent_run_error=PRIVATE if failed else None)
	payload = sink.capture.call_args.kwargs
	assert PRIVATE not in json.dumps(payload)
	assert payload['properties']['success'] is not failed
	assert payload['properties']['total_tokens'] == 120


def test_agent_event_has_no_private_content_before_transport():
	received = []
	history = Mock()
	history.judgement.return_value = None
	history.total_duration_seconds.return_value = 1.0
	history.is_successful.return_value = True
	token_cost = Mock()
	token_cost.get_usage_tokens_for_model.return_value = SimpleNamespace(
		prompt_tokens=1, completion_tokens=2, prompt_cached_tokens=0, total_tokens=3
	)
	agent = SimpleNamespace(
		task=PRIVATE,
		llm=SimpleNamespace(model='test-model', provider='test-provider'),
		token_cost_service=token_cost,
		history=history,
		telemetry=SimpleNamespace(capture=received.append),
		settings=SimpleNamespace(max_actions_per_step=3, use_vision=False),
		version='test-version',
		source='pip',
		state=SimpleNamespace(n_steps=1),
	)
	Agent._log_agent_event(agent, max_steps=10, agent_run_error=PRIVATE)
	assert len(received) == 1
	assert PRIVATE not in json.dumps(vars(received[0]))
	assert received[0].task == ''
	assert received[0].action_history == []
	assert received[0].error_message is None
