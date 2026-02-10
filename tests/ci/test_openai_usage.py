"""Test OpenAI usage token counting."""

from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.completion_usage import CompletionTokensDetails, CompletionUsage, PromptTokensDetails

from browser_use.llm.openai.chat import ChatOpenAI


def _make_response(
	completion_tokens: int,
	prompt_tokens: int,
	total_tokens: int,
	reasoning_tokens: int | None = None,
	cached_tokens: int | None = None,
) -> ChatCompletion:
	"""Build a real ChatCompletion with the given usage numbers."""
	completion_details = CompletionTokensDetails(reasoning_tokens=reasoning_tokens) if reasoning_tokens is not None else None
	prompt_details = PromptTokensDetails(cached_tokens=cached_tokens) if cached_tokens is not None else None

	return ChatCompletion(
		id='chatcmpl-test',
		choices=[Choice(finish_reason='stop', index=0, message=ChatCompletionMessage(role='assistant', content='test'))],
		created=1234567890,
		model='o4-mini',
		object='chat.completion',
		usage=CompletionUsage(
			completion_tokens=completion_tokens,
			prompt_tokens=prompt_tokens,
			total_tokens=total_tokens,
			completion_tokens_details=completion_details,
			prompt_tokens_details=prompt_details,
		),
	)


def test_get_usage_does_not_double_count_reasoning_tokens():
	"""OpenAI includes reasoning_tokens inside completion_tokens — adding them again inflates ~2x."""
	response = _make_response(completion_tokens=500, prompt_tokens=100, total_tokens=600, reasoning_tokens=400)
	client = ChatOpenAI(model='o4-mini')
	usage = client._get_usage(response)

	assert usage is not None
	assert usage.completion_tokens == 500
	assert usage.prompt_tokens == 100
	assert usage.total_tokens == 600


def test_get_usage_no_reasoning_tokens():
	"""Non-reasoning models return no completion_tokens_details — should still work."""
	response = _make_response(completion_tokens=200, prompt_tokens=50, total_tokens=250)
	client = ChatOpenAI(model='gpt-4o')
	usage = client._get_usage(response)

	assert usage is not None
	assert usage.completion_tokens == 200
	assert usage.prompt_tokens == 50
	assert usage.total_tokens == 250


def test_get_usage_with_cached_prompt_tokens():
	"""Cached prompt tokens should propagate correctly."""
	response = _make_response(completion_tokens=300, prompt_tokens=100, total_tokens=400, cached_tokens=60)
	client = ChatOpenAI(model='gpt-4o')
	usage = client._get_usage(response)

	assert usage is not None
	assert usage.prompt_cached_tokens == 60


def test_get_usage_none_when_no_usage():
	"""Should return None when response.usage is None."""
	response = ChatCompletion(
		id='chatcmpl-test',
		choices=[Choice(finish_reason='stop', index=0, message=ChatCompletionMessage(role='assistant', content='test'))],
		created=1234567890,
		model='o4-mini',
		object='chat.completion',
		usage=None,
	)
	client = ChatOpenAI(model='o4-mini')
	usage = client._get_usage(response)

	assert usage is None
