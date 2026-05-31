from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import BaseModel

from browser_use import Agent
from browser_use.agent.runtime.tools import NativeToolResult
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


class NativeFileWriteLLM:
	model = 'native-file-write-llm'
	provider = 'openai'
	name = 'native-file-write-llm'
	model_name = 'native-file-write-llm'
	_verified_api_keys = True
	supports_native_tool_calling = True

	async def ainvoke(self, messages, output_format=None, **kwargs):
		return ChatInvokeCompletion(
			completion='',
			usage=None,
			stop_reason='tool_calls',
			tool_calls=[
				ToolCall(
					id='file_write_call_1',
					function=Function(
						name='file_write',
						arguments='{"path":"reports/native.txt","content":"native-file-ok","create_parent_dirs":true}',
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
	assert any(tool['function']['name'] == 'browser_get_html' for tool in llm.last_kwargs['tools'])
	assert any(tool['function']['name'] == 'browser_get_accessibility_tree' for tool in llm.last_kwargs['tools'])
	assert any(tool['function']['name'] == 'browser_fetch' for tool in llm.last_kwargs['tools'])
	assert any(tool['function']['name'] == 'file_read' for tool in llm.last_kwargs['tools'])
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
	assert [item.kind for item in agent._message_manager.state.context_items][-2:] == ['tool_call', 'tool_result']

	rendered_context = agent._message_manager.build_typed_context(_browser_state()).render()
	assert '<tool_call id="call_1" name="browser_navigate">' in rendered_context
	assert '<tool_result name="browser_navigate" id="call_1">' in rendered_context


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


@pytest.mark.asyncio
async def test_agent_executes_pure_native_file_tool_without_legacy_action_executor(monkeypatch) -> None:
	llm = NativeFileWriteLLM()
	agent = Agent(task='Write a file through a native tool', llm=cast(Any, llm))

	async def fail_execute_action(*args, **kwargs):
		raise AssertionError('pure native file tools should not use the legacy action executor')

	monkeypatch.setattr(agent.tools.registry, 'execute_action', fail_execute_action)

	output = await agent.get_model_output([UserMessage(content='Write native-file-ok to a file')])

	assert output.action[0].model_dump(exclude_none=True) == {'wait': {'seconds': 0}}
	assert output.native_tool_calls[0].function.name == 'file_write'

	agent.state.last_model_output = output
	await agent._execute_actions()

	assert agent.state.last_result is not None
	assert agent.state.last_result[0].error is None
	assert 'Wrote 14 characters' in (agent.state.last_result[0].extracted_content or '')
	assert (agent.file_system.get_dir() / 'reports' / 'native.txt').read_text(encoding='utf-8') == 'native-file-ok'
	assert output.native_tool_results[0].tool_name == 'file_write'
	assert output.native_tool_results[0].structured_content['appended'] is False


@pytest.mark.asyncio
async def test_agent_executes_action_model_initial_actions_through_native_router(monkeypatch) -> None:
	llm = NativeDoneLLM()
	agent = Agent(task='Use initial wait', llm=cast(Any, llm))
	action = agent.ActionModel(**{'wait': {'seconds': 0}})

	async def fail_execute_action(*args, **kwargs):
		raise AssertionError('native action-model adapter should not use the legacy action executor')

	monkeypatch.setattr(agent.tools.registry, 'execute_action', fail_execute_action)

	results, native_results, tool_calls = await agent.multi_act_action_models_native([action])

	assert results[0].error is None
	assert results[0].extracted_content == 'Waited for 0 seconds'
	assert native_results[0].tool_name == 'browser_wait'
	assert tool_calls[0].function.name == 'browser_wait'


@pytest.mark.asyncio
async def test_initial_actions_use_native_model_output_context(monkeypatch) -> None:
	llm = NativeDoneLLM()
	agent = Agent(
		task='Run an initial action',
		llm=cast(Any, llm),
		initial_actions=[{'wait': {'seconds': 0}}],
	)

	async def fail_multi_act(*args, **kwargs):
		raise AssertionError('initial actions should avoid legacy multi_act when native tools are enabled')

	async def fake_native_initial_actions(actions):
		tool_call = ToolCall(
			id='initial-call',
			function=Function(name='browser_wait', arguments='{"seconds":0}'),
		)
		native_result = NativeToolResult(
			tool_name='browser_wait',
			call_id='initial-call',
			content='Waited for 0 seconds',
			structured_content={'seconds': 0},
		)
		return [ActionResult(extracted_content='Waited for 0 seconds')], [native_result], [tool_call]

	monkeypatch.setattr(agent, 'multi_act', fail_multi_act)
	monkeypatch.setattr(agent, 'multi_act_action_models_native', fake_native_initial_actions)

	await agent._execute_initial_actions()

	assert agent.state.last_result is not None
	assert agent.state.last_model_output is not None
	assert agent.state.last_model_output.native_tool_calls[0].function.name == 'browser_wait'
	assert agent.state.last_model_output.native_tool_results[0].content == 'Waited for 0 seconds'


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
