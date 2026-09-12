"""Usage accounting for the Anthropic chat models.

Anthropic reports cached prompt tokens in `cache_read_input_tokens`, which is
*not* included in `input_tokens`. `_get_usage` already adds it to
`prompt_tokens`, so `total_tokens` has to add it too or the invariant
`total_tokens == prompt_tokens + completion_tokens` breaks whenever prompt
caching is active.
"""

from types import SimpleNamespace
from typing import Any

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.aws.chat_anthropic import ChatAnthropicBedrock


def _response(input_tokens: int, output_tokens: int, cache_read: int, cache_creation: int = 0) -> Any:
	usage = SimpleNamespace(
		input_tokens=input_tokens,
		output_tokens=output_tokens,
		cache_read_input_tokens=cache_read,
		cache_creation_input_tokens=cache_creation,
		cache_creation=None,
	)
	return SimpleNamespace(usage=usage)


def test_bedrock_total_includes_cache_read():
	usage = ChatAnthropicBedrock()._get_usage(_response(input_tokens=500, output_tokens=200, cache_read=10_000))
	assert usage is not None
	assert usage.prompt_tokens == 10_500
	assert usage.completion_tokens == 200
	assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
	assert usage.total_tokens == 10_700


def test_anthropic_total_includes_cache_read():
	usage = ChatAnthropic(model='claude-sonnet-4-6')._get_usage(_response(input_tokens=500, output_tokens=200, cache_read=10_000))
	assert usage is not None
	assert usage.prompt_tokens == 10_500
	assert usage.completion_tokens == 200
	assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
	assert usage.total_tokens == 10_700


def test_total_unchanged_without_cache():
	for model in (ChatAnthropicBedrock(), ChatAnthropic(model='claude-sonnet-4-6')):
		usage = model._get_usage(_response(input_tokens=500, output_tokens=200, cache_read=0))
		assert usage is not None
		assert usage.total_tokens == 700
		assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
