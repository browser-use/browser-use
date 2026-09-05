from types import SimpleNamespace

import pytest

"""Test Anthropic model button click."""

from browser_use.llm.anthropic.chat import ChatAnthropic
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_anthropic_claude_sonnet_4_6(httpserver):
	"""Test Anthropic claude-sonnet-4-6 can click a button."""
	await run_model_button_click_test(
		model_class=ChatAnthropic,
		model_name='claude-sonnet-4-6',
		api_key_env='ANTHROPIC_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)


def _response(input_tokens, output_tokens, cache_read=0, cache_creation=0):
	return SimpleNamespace(
		usage=SimpleNamespace(
			input_tokens=input_tokens,
			output_tokens=output_tokens,
			cache_read_input_tokens=cache_read,
			cache_creation_input_tokens=cache_creation,
			cache_creation=None,
		)
	)


def test_total_tokens_counts_cache_reads_like_prompt_tokens_does():
	"""Anthropic reports input_tokens excluding cache reads, so both must add them."""
	model = ChatAnthropic(model='claude-sonnet-4-5-20250929', api_key='x')

	usage = model._get_usage(_response(input_tokens=1000, output_tokens=200, cache_read=5000))

	assert usage.prompt_tokens == 6000
	assert usage.completion_tokens == 200
	assert usage.total_tokens == 6200


@pytest.mark.parametrize(
	'input_tokens,output_tokens,cache_read',
	[(1000, 200, 0), (1000, 200, 5000), (0, 50, 900)],
)
def test_total_tokens_always_equals_prompt_plus_completion(input_tokens, output_tokens, cache_read):
	"""The invariant every other provider satisfies, with and without caching."""
	model = ChatAnthropic(model='claude-sonnet-4-5-20250929', api_key='x')

	usage = model._get_usage(_response(input_tokens, output_tokens, cache_read))

	assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
