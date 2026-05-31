from __future__ import annotations

from typing import Any, cast

import pytest

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


@pytest.mark.asyncio
async def test_agent_can_adapt_provider_native_tool_calls_to_actions() -> None:
	llm = NativeToolCallLLM()
	agent = Agent(task='Open example.com', llm=cast(Any, llm), use_native_tool_calls=True)

	output = await agent.get_model_output([UserMessage(content='Open example.com')])

	assert agent.settings.use_native_tool_calls is True
	assert agent.runtime_session.config.use_native_tool_calls is True
	assert llm.last_kwargs['output_format'] is None
	assert llm.last_kwargs['tool_choice'] == 'auto'
	assert any(tool['function']['name'] == 'browser_navigate' for tool in llm.last_kwargs['tools'])
	assert output.action[0].model_dump(exclude_none=True) == {'navigate': {'url': 'https://example.com', 'new_tab': False}}
