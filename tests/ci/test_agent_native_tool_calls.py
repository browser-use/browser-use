from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import BaseModel

from browser_use import Agent
from browser_use.llm.messages import Function, ToolCall, UserMessage
from browser_use.llm.views import ChatInvokeCompletion


class NativeToolCallLLM:
	model = 'native-tool-call-llm'
	provider = 'openai'
	name = 'native-tool-call-llm'
	model_name = 'native-tool-call-llm'
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


@pytest.mark.asyncio
async def test_agent_can_adapt_provider_native_tool_calls_to_actions() -> None:
	llm = NativeToolCallLLM()
	agent = Agent(task='Open example.com', llm=cast(Any, llm), use_native_tool_calls=True)

	output = await agent.get_model_output([UserMessage(content='Open example.com')])

	assert agent.settings.use_native_tool_calls is True
	assert agent.runtime_session.config.use_native_tool_calls is True
	assert 'Do not output JSON action objects' in agent._message_manager.system_prompt.text
	assert llm.last_kwargs['output_format'] is None
	assert llm.last_kwargs['tool_choice'] == 'auto'
	assert any(tool['function']['name'] == 'browser_navigate' for tool in llm.last_kwargs['tools'])
	assert output.action[0].model_dump(exclude_none=True) == {'navigate': {'url': 'https://example.com', 'new_tab': False}}


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
