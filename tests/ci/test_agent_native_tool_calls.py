from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import BaseModel

from browser_use import Agent
from browser_use.agent.views import ActionResult
from browser_use.browser.views import BrowserStateSummary, TabInfo
from browser_use.dom.views import SerializedDOMState
from browser_use.llm.messages import AssistantMessage, Function, ToolCall, ToolMessage, UserMessage
from browser_use.llm.views import ChatInvokeCompletion


class NativeToolCallLLM:
	model = 'native-tool-call-llm'
	provider = 'openai'
	name = 'native-tool-call-llm'
	model_name = 'native-tool-call-llm'
	_verified_api_keys = True
	supports_native_tool_calling = True
	supports_parallel_tool_calls = True

	def __init__(self) -> None:
		self.last_kwargs: dict[str, Any] = {}

	async def ainvoke(self, messages, output_format=None, **kwargs):
		self.last_kwargs = {'output_format': output_format, **kwargs}
		return ChatInvokeCompletion(
			completion='',
			usage=None,
			stop_reason='tool_calls',
			tool_calls=[
				ToolCall(
					id='call_1',
					function=Function(
						name='browser_navigate',
						arguments='{"url":"https://example.com","new_tab":false}',
					),
				)
			],
		)


class NativeStructuredDoneLLM:
	model = 'native-structured-done-llm'
	provider = 'openai'
	name = 'native-structured-done-llm'
	model_name = 'native-structured-done-llm'
	_verified_api_keys = True

	def __init__(self) -> None:
		self.last_kwargs: dict[str, Any] = {}

	async def ainvoke(self, messages, output_format=None, **kwargs):
		self.last_kwargs = {'output_format': output_format, **kwargs}
		return ChatInvokeCompletion(
			completion='',
			usage=None,
			stop_reason='tool_calls',
			tool_calls=[
				ToolCall(
					id='call_1',
					function=Function(
						name='browser_done',
						arguments='{"data":{"answer":"structured ok"},"success":true}',
					),
				)
			],
		)


class NativeDoneLLM:
	model = 'native-done-llm'
	provider = 'openai'
	name = 'native-done-llm'
	model_name = 'native-done-llm'
	_verified_api_keys = True
	supports_native_tool_calling = True

	async def ainvoke(self, messages, output_format=None, **kwargs):
		return ChatInvokeCompletion(
			completion='',
			usage=None,
			stop_reason='tool_calls',
			tool_calls=[
				ToolCall(
					id='done_call_1',
					function=Function(
						name='browser_done',
						arguments='{"text":"native loop done","success":true}',
					),
				)
			],
		)


def _browser_state() -> BrowserStateSummary:
	return BrowserStateSummary(
		url='https://example.com',
		title='Example',
		tabs=[TabInfo(target_id='target-1', url='https://example.com', title='Example')],
		dom_state=SerializedDOMState(_root=None, selector_map={}),
	)


@pytest.mark.asyncio
async def test_agent_can_adapt_provider_native_tool_calls_to_actions() -> None:
	llm = NativeToolCallLLM()
	agent = Agent(task='Open example.com', llm=cast(Any, llm))

	output = await agent.get_model_output([UserMessage(content='Open example.com')])

	assert agent.settings.use_native_tool_calls is True
	assert agent.settings.legacy_action_output is False
	assert agent.runtime_session.config.use_native_tool_calls is True
	assert agent.runtime_session.config.legacy_action_output is False
	assert 'Do not output JSON action objects' in agent._message_manager.system_prompt.text
	assert 'AgentOutput tool' not in agent._message_manager.system_prompt.text
	assert llm.last_kwargs['output_format'] is None
	assert llm.last_kwargs['tool_choice'] == 'required'
	assert any(tool['function']['name'] == 'browser_navigate' for tool in llm.last_kwargs['tools'])
	assert output.action[0].model_dump(exclude_none=True) == {'navigate': {'url': 'https://example.com', 'new_tab': False}}


@pytest.mark.asyncio
async def test_native_tool_results_are_returned_as_provider_tool_messages() -> None:
	llm = NativeToolCallLLM()
	agent = Agent(task='Open example.com', llm=cast(Any, llm))
	output = await agent.get_model_output([UserMessage(content='Open example.com')])

	agent._message_manager.prepare_step_state(
		browser_state_summary=_browser_state(),
		model_output=output,
		result=[ActionResult(extracted_content='Opened https://example.com')],
	)

	messages = agent._message_manager.get_messages()
	assert [message.role for message in messages[:3]] == ['system', 'assistant', 'tool']
	assert isinstance(messages[1], AssistantMessage)
	assert isinstance(messages[2], ToolMessage)
	assert messages[1].tool_calls[0].id == 'call_1'
	assert messages[2].tool_call_id == 'call_1'
	assert 'Opened https://example.com' in messages[2].content


@pytest.mark.asyncio
async def test_agent_executes_native_done_without_legacy_action_executor(monkeypatch) -> None:
	llm = NativeDoneLLM()
	agent = Agent(task='Finish directly', llm=cast(Any, llm))

	async def fail_execute_action(*args, **kwargs):
		raise AssertionError('native browser_done should not use the legacy action executor')

	monkeypatch.setattr(agent.tools.registry, 'execute_action', fail_execute_action)

	output = await agent.get_model_output([UserMessage(content='Finish directly')])
	agent.state.last_model_output = output
	await agent._execute_actions()

	assert agent.state.last_result is not None
	assert agent.state.last_result[0].is_done is True
	assert agent.state.last_result[0].extracted_content == 'native loop done'
	assert output.native_tool_results[0].call_id == 'done_call_1'
	assert output.native_tool_results[0].structured_content['is_done'] is True

	agent._message_manager.prepare_step_state(
		browser_state_summary=_browser_state(),
		model_output=output,
		result=agent.state.last_result,
	)
	tool_message = cast(ToolMessage, agent._message_manager.get_messages()[2])
	assert tool_message.tool_call_id == 'done_call_1'
	assert 'native loop done' in tool_message.content


def test_agent_can_force_legacy_action_output_for_native_capable_models() -> None:
	llm = NativeToolCallLLM()
	agent = Agent(task='Open example.com', llm=cast(Any, llm), legacy_action_output=True)

	assert agent.settings.use_native_tool_calls is False
	assert agent.settings.legacy_action_output is True
	assert agent.runtime_session.config.use_native_tool_calls is False
	assert agent.runtime_session.config.legacy_action_output is True
	assert 'Do not output JSON action objects' not in agent._message_manager.system_prompt.text


@pytest.mark.asyncio
async def test_agent_can_adapt_native_structured_done_to_legacy_executor() -> None:
	class MyOutput(BaseModel):
		answer: str

	llm = NativeStructuredDoneLLM()
	agent = Agent(
		task='Return a structured answer',
		llm=cast(Any, llm),
		output_model_schema=MyOutput,
		use_native_tool_calls=True,
	)

	output = await agent.get_model_output([UserMessage(content='Return the answer')])

	done_tool = next(tool for tool in llm.last_kwargs['tools'] if tool['function']['name'] == 'browser_done')
	assert 'StructuredDoneInput' in done_tool['function']['parameters']['title']
	assert output.action[0].model_dump(exclude_none=True) == {
		'done': {'success': True, 'data': {'answer': 'structured ok'}, 'files_to_display': []}
	}
