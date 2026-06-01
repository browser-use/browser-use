from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from anthropic.types import Message, ToolUseBlock, Usage
from google.genai import types

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.google.serializer import GoogleMessageSerializer
from browser_use.llm.messages import AssistantMessage, Function, ToolCall, ToolMessage, UserMessage


def _navigate_tool_schema() -> list[dict[str, Any]]:
	return [
		{
			'type': 'function',
			'function': {
				'name': 'browser_navigate',
				'description': 'Navigate to a URL.',
				'parameters': {
					'type': 'object',
					'properties': {'url': {'type': 'string'}},
					'required': ['url'],
				},
			},
		}
	]


@pytest.mark.asyncio
async def test_anthropic_ainvoke_returns_native_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
	create_kwargs: dict[str, Any] = {}

	class FakeMessages:
		async def create(self, **kwargs: Any) -> Message:
			create_kwargs.update(kwargs)
			return Message(
				id='msg_1',
				content=[
					ToolUseBlock(
						id='toolu_1',
						input={'url': 'https://example.com'},
						name='browser_navigate',
						type='tool_use',
					)
				],
				model='claude-sonnet-4-5',
				role='assistant',
				stop_reason='tool_use',
				stop_sequence=None,
				type='message',
				usage=Usage(input_tokens=1, output_tokens=2),
			)

	class FakeClient:
		messages = FakeMessages()

	chat = ChatAnthropic(model='claude-sonnet-4-5')
	monkeypatch.setattr(chat, 'get_client', lambda: FakeClient())

	response = await chat.ainvoke(
		[UserMessage(content='open example.com')], tools=_navigate_tool_schema(), tool_choice='required'
	)

	assert create_kwargs['tools'][0]['name'] == 'browser_navigate'
	assert create_kwargs['tool_choice']['type'] == 'any'
	assert response.completion == ''
	assert response.stop_reason == 'tool_use'
	assert len(response.tool_calls) == 1
	assert response.tool_calls[0].id == 'toolu_1'
	assert response.tool_calls[0].function.name == 'browser_navigate'
	assert response.tool_calls[0].function.arguments == '{"url": "https://example.com"}'


def test_google_serializer_supports_native_tool_protocol_messages() -> None:
	tool_call = ToolCall(
		id='call_1',
		function=Function(name='browser_navigate', arguments='{"url":"https://example.com"}'),
	)

	contents, _system = GoogleMessageSerializer.serialize_messages(
		[
			AssistantMessage(content=None, tool_calls=[tool_call]),
			ToolMessage(tool_call_id='call_1', content='{"ok": true}'),
		]
	)

	google_contents = cast(list[types.Content], contents)
	assert google_contents[0].role == 'model'
	assert google_contents[0].parts is not None
	function_call = google_contents[0].parts[0].function_call
	assert function_call is not None
	assert function_call.id == 'call_1'
	assert function_call.name == 'browser_navigate'
	assert function_call.args == {'url': 'https://example.com'}

	assert google_contents[1].role == 'user'
	assert google_contents[1].parts is not None
	function_response = google_contents[1].parts[0].function_response
	assert function_response is not None
	assert function_response.id == 'call_1'
	assert function_response.name == 'browser_navigate'
	assert function_response.response == {'ok': True}


@pytest.mark.asyncio
async def test_google_ainvoke_returns_native_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
	create_kwargs: dict[str, Any] = {}

	class FakeModels:
		async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
			create_kwargs.update(kwargs)
			return types.GenerateContentResponse(
				candidates=[
					types.Candidate(
						content=types.Content(
							role='model',
							parts=[
								types.Part(
									function_call=types.FunctionCall(
										id='call_1',
										name='browser_navigate',
										args={'url': 'https://example.com'},
									)
								)
							],
						),
						finish_reason=types.FinishReason.STOP,
					)
				]
			)

	class FakeClient:
		aio = SimpleNamespace(models=FakeModels())

	chat = ChatGoogle(model='gemini-3-flash-preview', temperature=0)
	monkeypatch.setattr(chat, 'get_client', lambda: FakeClient())

	response = await chat.ainvoke(
		[UserMessage(content='open example.com')], tools=_navigate_tool_schema(), tool_choice='required'
	)

	config = create_kwargs['config']
	assert config['tools'][0].function_declarations[0].name == 'browser_navigate'
	assert config['tool_config'].function_calling_config.mode == types.FunctionCallingConfigMode.ANY
	assert response.completion == ''
	assert len(response.tool_calls) == 1
	assert response.tool_calls[0].id == 'call_1'
	assert response.tool_calls[0].function.name == 'browser_navigate'
	assert response.tool_calls[0].function.arguments == '{"url": "https://example.com"}'
