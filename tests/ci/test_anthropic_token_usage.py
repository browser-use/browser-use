"""Token accounting for ChatAnthropic._get_usage.

Anthropic reports `input_tokens` *excluding* cache reads, so cache reads have to be
added back in to get the real prompt size. `total_tokens` must stay consistent with
that definition: every other provider satisfies
`total_tokens == prompt_tokens + completion_tokens`.
"""

from anthropic.types import Message, Usage
from anthropic.types.cache_creation import CacheCreation

from browser_use.llm.anthropic.chat import ChatAnthropic


def _message(usage: Usage) -> Message:
	return Message(
		id='msg_test',
		content=[],
		model='claude-sonnet-4-5-20250929',
		role='assistant',
		stop_reason='end_turn',
		stop_sequence=None,
		type='message',
		usage=usage,
	)


def _chat() -> ChatAnthropic:
	return ChatAnthropic(model='claude-sonnet-4-5-20250929', api_key='test-key-not-used')


def test_total_tokens_includes_cache_reads() -> None:
	"""With prompt caching active, total_tokens must not silently drop the cached prompt."""
	usage = _chat()._get_usage(
		_message(
			Usage(
				input_tokens=1000,
				output_tokens=200,
				cache_read_input_tokens=5000,
				cache_creation_input_tokens=0,
			)
		)
	)

	assert usage is not None
	assert usage.prompt_tokens == 6000
	assert usage.completion_tokens == 200
	assert usage.total_tokens == 6200
	assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens


def test_total_tokens_without_caching() -> None:
	"""No cache reads: the invariant is the plain input + output sum."""
	usage = _chat()._get_usage(
		_message(
			Usage(
				input_tokens=1000,
				output_tokens=200,
				cache_read_input_tokens=0,
				cache_creation_input_tokens=0,
			)
		)
	)

	assert usage is not None
	assert usage.prompt_tokens == 1000
	assert usage.total_tokens == 1200
	assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens


def test_total_tokens_with_null_cache_fields() -> None:
	"""Anthropic may omit the cache counters entirely; they must not poison the sum."""
	usage = _chat()._get_usage(
		_message(
			Usage(
				input_tokens=800,
				output_tokens=100,
				cache_read_input_tokens=None,
				cache_creation_input_tokens=None,
			)
		)
	)

	assert usage is not None
	assert usage.prompt_tokens == 800
	assert usage.total_tokens == 900
	assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens


def test_cache_creation_tokens_are_not_double_counted() -> None:
	"""Cache *writes* are already inside input_tokens, unlike cache reads."""
	usage = _chat()._get_usage(
		_message(
			Usage(
				input_tokens=1500,
				output_tokens=50,
				cache_read_input_tokens=2000,
				cache_creation_input_tokens=1200,
				cache_creation=CacheCreation(ephemeral_5m_input_tokens=1200, ephemeral_1h_input_tokens=0),
			)
		)
	)

	assert usage is not None
	assert usage.prompt_tokens == 3500
	assert usage.total_tokens == 3550
	assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
	assert usage.prompt_cache_creation_tokens == 1200
	assert usage.prompt_cache_creation_5m_tokens == 1200


def test_bedrock_anthropic_total_tokens_includes_cache_reads() -> None:
	"""The AWS Bedrock Anthropic client derives usage the same way and must agree."""
	from browser_use.llm.aws.chat_anthropic import ChatAnthropicBedrock

	usage = ChatAnthropicBedrock(model='anthropic.claude-sonnet-4-5-20250929-v1:0')._get_usage(
		_message(
			Usage(
				input_tokens=1000,
				output_tokens=200,
				cache_read_input_tokens=5000,
				cache_creation_input_tokens=0,
			)
		)
	)

	assert usage is not None
	assert usage.prompt_tokens == 6000
	assert usage.total_tokens == 6200
	assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
