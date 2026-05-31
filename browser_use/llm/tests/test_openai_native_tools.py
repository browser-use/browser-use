from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from browser_use.llm.messages import ToolMessage, UserMessage
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.openai.serializer import OpenAIMessageSerializer


def test_openai_serializer_supports_tool_result_messages() -> None:
	message = ToolMessage(tool_call_id='call_1', content='{"ok": true}')

	serialized = OpenAIMessageSerializer.serialize(message)

	assert serialized == {
		'role': 'tool',
		'content': '{"ok": true}',
		'tool_call_id': 'call_1',
	}


@pytest.mark.asyncio
async def test_openai_ainvoke_returns_native_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
	create_kwargs: dict[str, Any] = {}

	class FakeCompletions:
		async def create(self, **kwargs: Any) -> Any:
			create_kwargs.update(kwargs)
			return SimpleNamespace(
				choices=[
					SimpleNamespace(
						finish_reason='tool_calls',
						message=SimpleNamespace(
							content=None,
							tool_calls=[
								SimpleNamespace(
									id='call_1',
									type='function',
									function=SimpleNamespace(
										name='browser_navigate',
										arguments='{"url":"https://example.com"}',
									),
								)
							],
						),
					)
				],
				usage=None,
			)

	class FakeClient:
		chat = SimpleNamespace(completions=FakeCompletions())

	chat = ChatOpenAI(model='gpt-4.1-mini', temperature=0)
	monkeypatch.setattr(chat, 'get_client', lambda: FakeClient())

	tools = [
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
	response = await chat.ainvoke([UserMessage(content='open example.com')], tools=tools, tool_choice='auto')

	assert create_kwargs['tools'] == tools
	assert create_kwargs['tool_choice'] == 'auto'
	assert response.completion == ''
	assert response.stop_reason == 'tool_calls'
	assert len(response.tool_calls) == 1
	assert response.tool_calls[0].id == 'call_1'
	assert response.tool_calls[0].function.name == 'browser_navigate'
	assert response.tool_calls[0].function.arguments == '{"url":"https://example.com"}'


@pytest.mark.asyncio
async def test_openai_reasoning_models_omit_reasoning_effort_with_native_tools(monkeypatch: pytest.MonkeyPatch) -> None:
	create_kwargs: dict[str, Any] = {}

	class FakeCompletions:
		async def create(self, **kwargs: Any) -> Any:
			create_kwargs.update(kwargs)
			return SimpleNamespace(
				choices=[
					SimpleNamespace(
						finish_reason='tool_calls',
						message=SimpleNamespace(
							content=None,
							tool_calls=[
								SimpleNamespace(
									id='call_1',
									type='function',
									function=SimpleNamespace(name='browser_done', arguments='{"success":true,"text":"ok"}'),
								)
							],
						),
					)
				],
				usage=None,
			)

	class FakeClient:
		chat = SimpleNamespace(completions=FakeCompletions())

	chat = ChatOpenAI(model='gpt-5.4-mini', temperature=0)
	monkeypatch.setattr(chat, 'get_client', lambda: FakeClient())

	await chat.ainvoke(
		[UserMessage(content='finish')],
		tools=[
			{
				'type': 'function',
				'function': {
					'name': 'browser_done',
					'description': 'Complete the task.',
					'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}},
				},
			}
		],
		tool_choice='auto',
	)

	assert 'reasoning_effort' not in create_kwargs
	assert 'temperature' not in create_kwargs
	assert create_kwargs['tools'][0]['function']['name'] == 'browser_done'


class StructuredAnswer(BaseModel):
	answer: str


@pytest.mark.asyncio
async def test_openai_structured_output_tolerates_trailing_text(monkeypatch: pytest.MonkeyPatch) -> None:
	class FakeCompletions:
		async def create(self, **kwargs: Any) -> Any:
			return SimpleNamespace(
				choices=[
					SimpleNamespace(
						finish_reason='stop',
						message=SimpleNamespace(
							content='{"answer":"ok"}\n\nextra trailing text that strict JSON parsing rejects',
							tool_calls=None,
						),
					)
				],
				usage=None,
			)

	class FakeClient:
		chat = SimpleNamespace(completions=FakeCompletions())

	chat = ChatOpenAI(model='gpt-5.4-mini', temperature=0)
	monkeypatch.setattr(chat, 'get_client', lambda: FakeClient())

	response = await chat.ainvoke([UserMessage(content='answer with JSON')], StructuredAnswer)

	assert response.completion.answer == 'ok'


@pytest.mark.asyncio
async def test_openai_structured_output_tolerates_reasoning_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
	class FakeCompletions:
		async def create(self, **kwargs: Any) -> Any:
			return SimpleNamespace(
				choices=[
					SimpleNamespace(
						finish_reason='stop',
						message=SimpleNamespace(
							content='<think>I should answer with JSON.</think>\n```json\n{"answer":"ok"}\n```',
							tool_calls=None,
						),
					)
				],
				usage=None,
			)

	class FakeClient:
		chat = SimpleNamespace(completions=FakeCompletions())

	chat = ChatOpenAI(model='gpt-5.4-mini', temperature=0)
	monkeypatch.setattr(chat, 'get_client', lambda: FakeClient())

	response = await chat.ainvoke([UserMessage(content='answer with JSON')], StructuredAnswer)

	assert response.completion.answer == 'ok'
