"""Anthropic usage accounting: the total has to agree with its own parts.

Anthropic does not return a `total_tokens` field, so unlike every other
provider in this package these two files compute it themselves. Both compute it
from the raw `input_tokens`, which excludes cache reads, while `prompt_tokens`
one line above adds the cache read in. The result is a `ChatInvokeUsage` whose
total disagrees with `prompt_tokens + completion_tokens` on any cached call.

In an agent loop the system prompt and the accumulated history are re-read from
cache on every step, so within a few steps the cache read is most of the input
and the reported total is a small fraction of what was actually sent.
"""

from types import SimpleNamespace

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.aws.chat_anthropic import ChatAnthropicBedrock


def _response(input_tokens: int, output_tokens: int, cache_read: int = 0, cache_creation: int = 0):
	"""A minimal stand-in for an Anthropic Message, carrying only usage."""
	return SimpleNamespace(
		usage=SimpleNamespace(
			input_tokens=input_tokens,
			output_tokens=output_tokens,
			cache_read_input_tokens=cache_read,
			cache_creation_input_tokens=cache_creation,
			cache_creation=None,
		)
	)


def test_total_agrees_with_its_parts_on_a_cached_call():
	"""total_tokens must equal prompt_tokens + completion_tokens.

	`prompt_tokens` is documented as including the cached tokens, so a total
	that omits them contradicts the same object it is returned in.
	"""
	chat = ChatAnthropic(model='claude-sonnet-4-6', api_key='test')
	usage = chat._get_usage(_response(input_tokens=10, output_tokens=5, cache_read=1000))

	assert usage is not None
	assert usage.prompt_tokens == 1010
	assert usage.completion_tokens == 5
	assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
	assert usage.total_tokens == 1015


def test_bedrock_total_agrees_with_its_parts_on_a_cached_call():
	"""The Bedrock client serves the same models and carries the same defect."""
	chat = ChatAnthropicBedrock(model='anthropic.claude-sonnet-4-6-v1:0')
	# This overload annotates `response` as `Message` rather than `Any`, and the stand-in
	# carries only the `usage` attribute the method actually reads.
	usage = chat._get_usage(_response(input_tokens=10, output_tokens=5, cache_read=1000))  # type: ignore[arg-type]

	assert usage is not None
	assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
	assert usage.total_tokens == 1015


def test_uncached_call_is_unchanged():
	"""With no cache read the total is what it always was, so this is not a behaviour change."""
	chat = ChatAnthropic(model='claude-sonnet-4-6', api_key='test')
	usage = chat._get_usage(_response(input_tokens=10, output_tokens=5))

	assert usage is not None
	assert usage.prompt_tokens == 10
	assert usage.total_tokens == 15
