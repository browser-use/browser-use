from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

import pytest

from browser_use import Agent
from browser_use.agent.llm_debug_trace import (
	append_llm_debug_trace,
	llm_debug_trace_path,
	model_input_snapshot_paths,
	write_model_input_snapshot,
)
from browser_use.agent.runtime.context import BrowserContext, TaskItem
from browser_use.llm.messages import Function, ToolCall, UserMessage
from browser_use.llm.views import ChatInvokeCompletion


class StructuredTraceLLM:
	model = 'structured-trace-llm'
	provider = 'mock'
	name = 'structured-trace-llm'
	model_name = 'structured-trace-llm'
	_verified_api_keys = True

	async def ainvoke(self, messages: list[Any], output_format=None, **kwargs: Any) -> ChatInvokeCompletion[Any]:
		assert output_format is not None
		return ChatInvokeCompletion(
			completion=output_format.model_validate(
				{
					'evaluation_previous_goal': 'No previous goal.',
					'memory': 'Need to finish.',
					'next_goal': 'Return done.',
					'action': [{'done': {'text': 'ok', 'success': True}}],
				}
			),
			usage=None,
			stop_reason='stop',
		)


class NativeTraceLLM:
	model = 'native-trace-llm'
	provider = 'mock'
	name = 'native-trace-llm'
	model_name = 'native-trace-llm'
	_verified_api_keys = True

	async def ainvoke(self, messages: list[Any], output_format=None, **kwargs: Any) -> ChatInvokeCompletion[str]:
		return ChatInvokeCompletion(
			completion='',
			usage=None,
			stop_reason='tool_calls',
			tool_calls=[
				ToolCall(
					id='call_1',
					function=Function(name='browser_done', arguments='{"success":true,"text":"native ok"}'),
				)
			],
		)


def _read_trace(path: Path) -> list[dict[str, Any]]:
	return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


@pytest.mark.asyncio
async def test_llm_debug_trace_is_not_written_outside_debug_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('BROWSER_USE_LOGGING_LEVEL', 'info')
	logger = logging.getLogger('browser_use.tests.llm_trace.disabled')
	logger.setLevel(logging.INFO)

	await append_llm_debug_trace(
		agent_directory=tmp_path,
		logger=logger,
		event='llm_call_start',
		step=0,
		session_id='session',
		llm=StructuredTraceLLM(),
		messages=[UserMessage(content='hello')],
	)

	assert not llm_debug_trace_path(tmp_path).exists()


@pytest.mark.asyncio
async def test_model_input_snapshot_is_written_in_debug_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('BROWSER_USE_LOGGING_LEVEL', 'debug')
	logger = logging.getLogger('browser_use.tests.llm_trace.snapshot')
	context = BrowserContext(items=[TaskItem(text='Find the answer')])

	await write_model_input_snapshot(
		agent_directory=tmp_path,
		logger=logger,
		step=3,
		session_id='session',
		messages=[UserMessage(content='hello model')],
		typed_context=context,
	)

	json_path, text_path = model_input_snapshot_paths(tmp_path, 3)
	assert json_path.exists()
	assert text_path.exists()

	record = json.loads(json_path.read_text(encoding='utf-8'))
	assert record['event'] == 'model_input_snapshot'
	assert record['step'] == 3
	assert record['messages'][0]['content'] == 'hello model'
	assert record['rendered_typed_context'] == context.render()
	assert record['typed_context']['items'][0]['kind'] == 'task'

	text = text_path.read_text(encoding='utf-8')
	assert 'role=user' in text
	assert 'hello model' in text
	assert '<user_request>' in text


@pytest.mark.asyncio
async def test_structured_output_llm_debug_trace_captures_messages_actions_and_response(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	monkeypatch.setenv('BROWSER_USE_LOGGING_LEVEL', 'debug')
	llm = StructuredTraceLLM()
	agent = Agent(task='Return done', llm=cast(Any, llm), use_vision=False)

	output = await agent.get_model_output([UserMessage(content='Return done now')])

	done_action = output.action[0].model_dump(exclude_none=True)['done']
	assert done_action['text'] == 'ok'
	assert done_action['success'] is True
	trace_records = _read_trace(llm_debug_trace_path(agent.agent_directory))

	start = trace_records[0]
	result = trace_records[1]
	assert start['event'] == 'llm_call_start'
	assert start['messages'][0]['content'] == 'Return done now'
	assert start['output_format']['name'] == 'AgentOutput'
	assert start['invoke_kwargs']['output_format']['name'] == 'AgentOutput'
	assert any(action['name'] == 'done' for action in start['registered_actions'])
	assert any(action['name'] == 'navigate' for action in start['registered_actions'])

	assert result['event'] == 'llm_call_result'
	assert result['response']['completion']['action'][0]['done']['text'] == 'ok'
	assert result['response']['stop_reason'] == 'stop'


@pytest.mark.asyncio
async def test_native_tool_llm_debug_trace_captures_provider_tool_schemas(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	monkeypatch.setenv('BROWSER_USE_LOGGING_LEVEL', 'debug')
	llm = NativeTraceLLM()
	agent = Agent(task='Return done', llm=cast(Any, llm), use_vision=False, use_native_tool_calls=True)

	output = await agent.get_model_output([UserMessage(content='Call done')])

	done_action = output.action[0].model_dump(exclude_none=True)['done']
	assert done_action['text'] == 'native ok'
	assert done_action['success'] is True
	trace_records = _read_trace(llm_debug_trace_path(agent.agent_directory))

	start = trace_records[0]
	result = trace_records[1]
	assert start['event'] == 'llm_call_start'
	assert start['invoke_kwargs']['output_format'] is None
	assert start['invoke_kwargs']['tool_choice'] == 'required'
	assert any(tool['function']['name'] == 'browser_done' for tool in start['native_tools'])
	assert any(tool['function']['name'] == 'browser_done' for tool in start['invoke_kwargs']['tools'])

	assert result['event'] == 'llm_call_result'
	assert result['response']['tool_calls'][0]['function']['name'] == 'browser_done'
