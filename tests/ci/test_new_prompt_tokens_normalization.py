"""Invariant tests for cache-token normalization and new_prompt_tokens.

Follow-up to the closed browser-use#5319: `new_prompt_tokens` returned the raw,
cache-inclusive prompt count while the cost basis used prompt_tokens minus
cache-read. Per the maintainer's guidance, each adapter now normalizes to the
convention the Anthropic adapters already use -- prompt_tokens = real input +
cache-read, with cache-creation tracked separately -- and new_prompt_tokens is
computed against that basis, clamped so malformed usage can't go negative.
"""

import types

import pytest

from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import ModelPricing

INPUT_COST = 0.10 / 1_000_000
OUTPUT_COST = 0.20 / 1_000_000
CACHE_READ_COST = 0.02 / 1_000_000
CACHE_CREATION_COST = 0.12 / 1_000_000


@pytest.fixture
def token_cost(monkeypatch: pytest.MonkeyPatch) -> TokenCost:
	async def fake_pricing(model_name: str) -> ModelPricing:
		return ModelPricing(
			model=model_name,
			input_cost_per_token=INPUT_COST,
			output_cost_per_token=OUTPUT_COST,
			cache_read_input_token_cost=CACHE_READ_COST,
			cache_creation_input_token_cost=CACHE_CREATION_COST,
			max_tokens=None,
			max_input_tokens=None,
			max_output_tokens=None,
		)

	monkeypatch.setattr('browser_use.tokens.service.get_openrouter_model_pricing', fake_pricing)
	cost = TokenCost(include_cost=True)
	cost._initialized = True
	cost._pricing_data = {}
	return cost


def _usage(prompt_tokens: int, cached: int | None = None, creation: int | None = None, completion_tokens: int = 40):
	return ChatInvokeUsage(
		prompt_tokens=prompt_tokens,
		prompt_cached_tokens=cached,
		prompt_cache_creation_tokens=creation,
		prompt_image_tokens=None,
		completion_tokens=completion_tokens,
		total_tokens=prompt_tokens + completion_tokens,
	)


# --- service.calculate_cost invariants ---------------------------------------


async def test_new_prompt_tokens_excludes_cache_read(token_cost: TokenCost):
	# Normalized usage: 100 real input + 20 cache-read -> prompt_tokens 120.
	result = await token_cost.calculate_cost('gpt-4o', _usage(120, cached=20))
	assert result is not None
	assert result.new_prompt_tokens == 100  # not the raw inclusive 120
	assert result.new_prompt_cost == pytest.approx(100 * INPUT_COST)
	assert result.prompt_read_cached_tokens == 20


async def test_cache_creation_not_counted_as_new(token_cost: TokenCost):
	# The maintainer's example after adapter normalization: input 100 + read 20
	# = prompt_tokens 120, with creation 30 tracked separately (not in prompt_tokens).
	result = await token_cost.calculate_cost('claude', _usage(120, cached=20, creation=30))
	assert result is not None
	assert result.new_prompt_tokens == 100
	assert result.prompt_read_cached_tokens == 20
	assert result.prompt_cached_creation_tokens == 30
	# new + read + creation reconstructs the 150 tokens LiteLLM originally reported.
	assert result.new_prompt_tokens + result.prompt_read_cached_tokens + result.prompt_cached_creation_tokens == 150


async def test_negative_guard_when_cached_exceeds_prompt(token_cost: TokenCost):
	result = await token_cost.calculate_cost('gpt-4o', _usage(50, cached=80))
	assert result is not None
	assert result.new_prompt_tokens == 0
	assert result.new_prompt_cost == 0


async def test_no_cache_is_all_new(token_cost: TokenCost):
	result = await token_cost.calculate_cost('gpt-4o', _usage(100))
	assert result is not None
	assert result.new_prompt_tokens == 100


# --- adapter normalization ----------------------------------------------------


def test_litellm_adapter_strips_cache_creation_from_prompt_tokens():
	chat = pytest.importorskip('browser_use.llm.litellm.chat')
	# LiteLLM-Anthropic rolls cache-creation into prompt_tokens: 100 input + 20 read
	# + 30 creation = 150.
	response = types.SimpleNamespace(
		usage=types.SimpleNamespace(
			prompt_tokens=150,
			completion_tokens=40,
			cache_read_input_tokens=20,
			cache_creation_input_tokens=30,
		)
	)
	usage = chat.ChatLiteLLM._parse_usage(response)
	assert usage is not None
	assert usage.prompt_tokens == 120  # creation stripped -> input + read
	assert usage.prompt_cached_tokens == 20
	assert usage.prompt_cache_creation_tokens == 30


def test_bedrock_adapter_populates_cache_tokens():
	chat = pytest.importorskip('browser_use.llm.aws.chat_bedrock')
	response = {
		'usage': {
			'inputTokens': 100,
			'outputTokens': 40,
			'totalTokens': 190,
			'cacheReadInputTokens': 20,
			'cacheWriteInputTokens': 30,
		}
	}
	# _get_usage only reads `response`, so an unbound call is fine and avoids
	# constructing a real Bedrock client.
	usage = chat.ChatAWSBedrock._get_usage(None, response)
	assert usage is not None
	assert usage.prompt_tokens == 120  # input + cache-read (Anthropic convention)
	assert usage.prompt_cached_tokens == 20
	assert usage.prompt_cache_creation_tokens == 30
