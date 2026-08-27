"""Tests for the ChatVolcengine (Volcengine Ark) request and usage handling."""

from unittest.mock import AsyncMock, patch

from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.completion_usage import CompletionUsage, PromptTokensDetails
from pydantic import BaseModel

from browser_use.llm.messages import UserMessage
from browser_use.llm.volcengine.chat import ChatVolcengine

# A syntactically-valid key so the constructor doesn't bail before we reach the
# code under test. These unit tests never hit the network.
TEST_API_KEY = 'test-key-not-real'


class Answer(BaseModel):
	answer: str


def _completion(*, content: str, cached_tokens: int | None = None) -> ChatCompletion:
	"""Build an Ark-shaped ChatCompletion. Ark reports prompt_tokens_details.cached_tokens."""
	prompt_details = PromptTokensDetails(cached_tokens=cached_tokens) if cached_tokens is not None else None
	return ChatCompletion(
		id='chatcmpl-test',
		choices=[
			Choice(
				finish_reason='stop',
				index=0,
				message=ChatCompletionMessage(role='assistant', content=content),
			)
		],
		created=0,
		model='doubao-seed-2-1-pro-260628',
		object='chat.completion',
		usage=CompletionUsage(
			prompt_tokens=11,
			completion_tokens=7,
			total_tokens=18,
			prompt_tokens_details=prompt_details,
		),
	)


async def _capture(llm: ChatVolcengine, response: ChatCompletion, output_format=None):
	"""Invoke the model and return (result, kwargs the SDK was called with)."""
	create = AsyncMock(return_value=response)
	with patch.object(type(llm.get_client().chat.completions), 'create', create):
		result = await llm.ainvoke([UserMessage(content='question')], output_format)
	assert create.await_args is not None, 'the SDK create() was never awaited'
	return result, create.await_args.kwargs


async def test_defaults_target_ark_and_omit_unset_params():
	"""Unset generation params must not be sent — Ark rejects some as invalid combinations."""
	llm = ChatVolcengine(api_key=TEST_API_KEY)

	assert llm.provider == 'volcengine'
	assert str(llm.base_url) == 'https://ark.cn-beijing.volces.com/api/v3'
	assert llm.model == 'doubao-seed-2-1-pro-260628'

	_, kwargs = await _capture(llm, _completion(content='hi'))

	assert kwargs['model'] == 'doubao-seed-2-1-pro-260628'
	for unset in ('temperature', 'top_p', 'seed', 'max_tokens', 'reasoning_effort'):
		assert unset not in kwargs


async def test_reasoning_effort_is_forwarded():
	"""Ark grades thinking depth via reasoning_effort rather than a separate toggle."""
	llm = ChatVolcengine(api_key=TEST_API_KEY, reasoning_effort='high', temperature=0.5)

	_, kwargs = await _capture(llm, _completion(content='hi'))

	assert kwargs['reasoning_effort'] == 'high'
	assert kwargs['temperature'] == 0.5


async def test_usage_includes_cached_prompt_tokens():
	llm = ChatVolcengine(api_key=TEST_API_KEY)

	result, _ = await _capture(llm, _completion(content='hi', cached_tokens=4))

	assert result.completion == 'hi'
	assert result.usage is not None
	assert result.usage.prompt_tokens == 11
	assert result.usage.prompt_cached_tokens == 4
	assert result.usage.completion_tokens == 7
	assert result.usage.total_tokens == 18


async def test_structured_output_uses_strict_json_schema():
	"""Ark accepts strict json_schema response formats, so we don't need a tool-call detour."""
	llm = ChatVolcengine(api_key=TEST_API_KEY)

	result, kwargs = await _capture(llm, _completion(content='{"answer": "42"}'), Answer)

	assert isinstance(result.completion, Answer)
	assert result.completion.answer == '42'
	assert kwargs['response_format']['type'] == 'json_schema'
	assert kwargs['response_format']['json_schema']['strict'] is True


async def test_api_key_falls_back_to_ark_env_var(monkeypatch):
	"""Without this, AsyncOpenAI would read OPENAI_API_KEY and send the wrong credential."""
	monkeypatch.setenv('ARK_API_KEY', 'ark-from-env')
	monkeypatch.setenv('OPENAI_API_KEY', 'openai-should-not-be-used')

	llm = ChatVolcengine()

	assert llm.get_client().api_key == 'ark-from-env'
