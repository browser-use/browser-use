from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.groq.chat import ChatGroq


class GroqStructuredAnswer(BaseModel):
	answer: str


@pytest.mark.asyncio
async def test_groq_tool_calling_structured_output_reads_function_arguments(monkeypatch):
	chat = ChatGroq(model='moonshotai/kimi-k2-instruct')

	async def fake_tool_calling(groq_messages, output_format, schema):
		return SimpleNamespace(
			usage=None,
			choices=[
				SimpleNamespace(
					message=SimpleNamespace(
						content=None,
						tool_calls=[
							SimpleNamespace(function=SimpleNamespace(arguments='{"answer": "ok"}')),
						],
					)
				)
			],
		)

	monkeypatch.setattr(chat, '_invoke_with_tool_calling', fake_tool_calling)

	result = await chat._invoke_structured_output([], GroqStructuredAnswer)

	assert result.completion == GroqStructuredAnswer(answer='ok')
	assert result.usage is None


@pytest.mark.asyncio
async def test_groq_tool_calling_structured_output_accepts_dict_arguments(monkeypatch):
	chat = ChatGroq(model='moonshotai/kimi-k2-instruct')

	async def fake_tool_calling(groq_messages, output_format, schema):
		return SimpleNamespace(
			usage=None,
			choices=[
				SimpleNamespace(
					message=SimpleNamespace(
						content=None,
						tool_calls=[
							SimpleNamespace(function=SimpleNamespace(arguments={'answer': 'ok'})),
						],
					)
				)
			],
		)

	monkeypatch.setattr(chat, '_invoke_with_tool_calling', fake_tool_calling)

	result = await chat._invoke_structured_output([], GroqStructuredAnswer)

	assert result.completion == GroqStructuredAnswer(answer='ok')
	assert result.usage is None


@pytest.mark.asyncio
async def test_groq_tool_calling_structured_output_requires_tool_calls(monkeypatch):
	chat = ChatGroq(model='moonshotai/kimi-k2-instruct')

	async def fake_tool_calling(groq_messages, output_format, schema):
		return SimpleNamespace(
			usage=None,
			choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[]))],
		)

	monkeypatch.setattr(chat, '_invoke_with_tool_calling', fake_tool_calling)

	with pytest.raises(ModelProviderError, match='No tool calls in response'):
		await chat._invoke_structured_output([], GroqStructuredAnswer)


@pytest.mark.asyncio
async def test_groq_tool_calling_structured_output_requires_tool_call_arguments(monkeypatch):
	chat = ChatGroq(model='moonshotai/kimi-k2-instruct')

	async def fake_tool_calling(groq_messages, output_format, schema):
		return SimpleNamespace(
			usage=None,
			choices=[
				SimpleNamespace(
					message=SimpleNamespace(
						content=None,
						tool_calls=[
							SimpleNamespace(function=SimpleNamespace(arguments=None)),
						],
					)
				)
			],
		)

	monkeypatch.setattr(chat, '_invoke_with_tool_calling', fake_tool_calling)

	with pytest.raises(ModelProviderError, match='No tool call arguments in response'):
		await chat._invoke_structured_output([], GroqStructuredAnswer)
