"""Unit tests for the DeepSeek chat client (v4 JSON-output compatibility + setup regressions)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from browser_use.llm.deepseek.chat import ChatDeepSeek, _repair_json_control_chars
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import SystemMessage, UserMessage


class _SimpleOutput(BaseModel):
	action: list[dict[str, object]] = Field(..., min_length=1)


def _client_with(response):
	client = MagicMock()
	client.chat.completions.create = AsyncMock(return_value=response)
	return client


def _tool_call_response(args: str):
	tool_call = SimpleNamespace(function=SimpleNamespace(arguments=args))
	message = SimpleNamespace(content=None, tool_calls=[tool_call])
	return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _json_response(content: str):
	message = SimpleNamespace(content=content, tool_calls=None)
	return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _messages():
	return [
		SystemMessage(content='You are a browser automation agent.'),
		UserMessage(content='Search Google for browser automation.'),
	]


def test_repair_json_control_chars_escapes_raw_control_chars_inside_strings():
	broken = '{\n  "thinking": "line1\nline2\tend",\n  "action": [{"search": {"query": "a", "engine": "google"}}]\n}'
	repaired = _repair_json_control_chars(broken)

	assert '\\u000a' in repaired and '\\u0009' in repaired
	assert _SimpleOutput.model_validate_json(repaired) is not None


async def test_repair_json_control_chars_keeps_structural_whitespace():
	content = '{\n  "action": [{"search": {"query": "a", "engine": "google"}}]\n}'
	assert _repair_json_control_chars(content) == content


@pytest.mark.asyncio
async def test_reasoning_model_uses_json_output_path():
	valid = '{"action": [{"search": {"query": "a", "engine": "google"}}]}'
	client = _client_with(_json_response(valid))
	llm = ChatDeepSeek(model='deepseek-v4-flash', api_key='test-key')

	with patch.object(ChatDeepSeek, '_client', return_value=client):
		result = await llm.ainvoke(_messages(), output_format=_SimpleOutput)

	kwargs = client.chat.completions.create.call_args.kwargs
	assert kwargs['response_format'] == {'type': 'json_object'}
	assert 'tools' not in kwargs
	assert kwargs['extra_body'] == {'thinking': {'type': 'disabled'}}
	assert result.completion.action == [{'search': {'query': 'a', 'engine': 'google'}}]


@pytest.mark.asyncio
async def test_json_path_repairs_raw_control_chars_before_validation():
	broken = '{"thinking": "line1\nline2", "action": [{"search": {"query": "a", "engine": "google"}}]}'
	client = _client_with(_json_response(broken))
	llm = ChatDeepSeek(model='deepseek-v4-pro', api_key='test-key')

	with patch.object(ChatDeepSeek, '_client', return_value=client):
		result = await llm.ainvoke(_messages(), output_format=_SimpleOutput)

	assert result.completion.action == [{'search': {'query': 'a', 'engine': 'google'}}]


@pytest.mark.asyncio
async def test_non_reasoning_model_keeps_function_calling_path():
	args = '{"action": [{"search": {"query": "a", "engine": "google"}}]}'
	client = _client_with(_tool_call_response(args))
	llm = ChatDeepSeek(model='deepseek-chat', api_key='test-key')

	with patch.object(ChatDeepSeek, '_client', return_value=client):
		result = await llm.ainvoke(_messages(), output_format=_SimpleOutput)

	kwargs = client.chat.completions.create.call_args.kwargs
	assert kwargs['tools']
	assert kwargs['tool_choice'] == {'type': 'function', 'function': {'name': '_SimpleOutput'}}
	assert 'response_format' not in kwargs
	assert result.completion.action == [{'search': {'query': 'a', 'engine': 'google'}}]


def test_provider_key_does_not_fall_back_to_openai_key(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('OPENAI_API_KEY', 'wrong-provider-key')
	monkeypatch.setenv('DEEPSEEK_API_KEY', 'deepseek-key')
	assert ChatDeepSeek(model='deepseek-v4-flash')._client().api_key == 'deepseek-key'

	monkeypatch.delenv('DEEPSEEK_API_KEY')
	with pytest.raises(ModelProviderError, match='Missing DeepSeek API key') as exc_info:
		ChatDeepSeek(model='deepseek-v4-flash')._client()
	assert exc_info.value.status_code == 401


def test_explicit_api_key_takes_precedence_over_env(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('DEEPSEEK_API_KEY', 'env-key')
	assert ChatDeepSeek(model='deepseek-v4-flash', api_key='explicit-key')._client().api_key == 'explicit-key'
