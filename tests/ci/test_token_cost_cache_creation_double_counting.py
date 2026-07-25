"""
Regression test for cache-creation token double-counting in cost calculation.

Bug: `uncached_prompt_tokens` only subtracted `prompt_cached_tokens` (cache-read
tokens), not `prompt_cache_creation_tokens`. This caused cache-creation tokens to
be charged at *both* `input_cost_per_token` (via new_prompt_cost) *and*
`cache_creation_input_token_cost` (via prompt_cache_creation_cost).

Anthropic's `input_tokens` (mapped to `prompt_tokens`) is the sum of:
  regular + cache_read + cache_creation
Each category has its own per-token rate, so they must be mutually exclusive in
the cost computation.
"""

import pytest

from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import ModelPricing


def _make_token_cost(monkeypatch: pytest.MonkeyPatch, pricing: ModelPricing) -> TokenCost:
	"""Helper to create a TokenCost instance with known pricing."""

	async def fake_openrouter_pricing(model_name: str) -> ModelPricing:
		return pricing

	monkeypatch.setattr('browser_use.tokens.service.get_openrouter_model_pricing', fake_openrouter_pricing)

	token_cost = TokenCost(include_cost=True)
	token_cost._initialized = True
	token_cost._pricing_data = {}
	return token_cost


# --- Anthropic-style cache creation (generic prompt_cache_creation_tokens) ---


@pytest.mark.asyncio
async def test_cache_creation_tokens_not_double_counted(monkeypatch: pytest.MonkeyPatch) -> None:
	"""Cache-creation tokens should only be charged at cache_creation rate, not also at input rate."""
	pricing = ModelPricing(
		model='anthropic/claude-sonnet-4-20250514',
		input_cost_per_token=3.0 / 1_000_000,
		output_cost_per_token=15.0 / 1_000_000,
		cache_read_input_token_cost=0.30 / 1_000_000,
		cache_creation_input_token_cost=3.75 / 1_000_000,
		max_tokens=None,
		max_input_tokens=None,
		max_output_tokens=None,
	)
	token_cost = _make_token_cost(monkeypatch, pricing)

	# prompt_tokens = 2000 total = 1200 regular + 500 cache_read + 300 cache_creation
	usage = ChatInvokeUsage(
		prompt_tokens=2000,
		prompt_cached_tokens=500,
		prompt_cache_creation_tokens=300,
		prompt_image_tokens=None,
		completion_tokens=100,
		total_tokens=2100,
	)

	cost = await token_cost.calculate_cost('anthropic/claude-sonnet-4-20250514', usage)

	assert cost is not None

	# Regular tokens = 2000 - 500 - 300 = 1200
	expected_new_prompt_cost = 1200 * (3.0 / 1_000_000)
	assert cost.new_prompt_cost == pytest.approx(expected_new_prompt_cost)

	# Cache read cost
	expected_cache_read_cost = 500 * (0.30 / 1_000_000)
	assert cost.prompt_read_cached_cost == pytest.approx(expected_cache_read_cost)

	# Cache creation cost (only at cache_creation rate)
	expected_cache_creation_cost = 300 * (3.75 / 1_000_000)
	assert cost.prompt_cache_creation_cost == pytest.approx(expected_cache_creation_cost)

	# Total prompt cost should be the sum of the three components
	expected_total_prompt = expected_new_prompt_cost + expected_cache_read_cost + expected_cache_creation_cost
	assert cost.prompt_cost == pytest.approx(expected_total_prompt)

	# Completion cost
	expected_completion_cost = 100 * (15.0 / 1_000_000)
	assert cost.completion_cost == pytest.approx(expected_completion_cost)

	# Total
	assert cost.total_cost == pytest.approx(expected_total_prompt + expected_completion_cost)


@pytest.mark.asyncio
async def test_no_cache_creation_tokens_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
	"""When there are no cache-creation tokens, behaviour is unchanged."""
	pricing = ModelPricing(
		model='openai/gpt-4o',
		input_cost_per_token=2.5 / 1_000_000,
		output_cost_per_token=10.0 / 1_000_000,
		cache_read_input_token_cost=1.25 / 1_000_000,
		cache_creation_input_token_cost=None,
		max_tokens=None,
		max_input_tokens=None,
		max_output_tokens=None,
	)
	token_cost = _make_token_cost(monkeypatch, pricing)

	usage = ChatInvokeUsage(
		prompt_tokens=1000,
		prompt_cached_tokens=200,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=50,
		total_tokens=1050,
	)

	cost = await token_cost.calculate_cost('openai/gpt-4o', usage)

	assert cost is not None
	# Regular = 1000 - 200 = 800
	assert cost.new_prompt_cost == pytest.approx(800 * (2.5 / 1_000_000))
	assert cost.prompt_read_cached_cost == pytest.approx(200 * (1.25 / 1_000_000))
	assert cost.prompt_cache_creation_cost is None


# --- Anthropic 5m/1h split cache creation tokens ---


@pytest.mark.asyncio
async def test_split_cache_creation_tokens_not_double_counted(monkeypatch: pytest.MonkeyPatch) -> None:
	"""5m/1h split cache-creation tokens should not be double-counted either."""
	pricing = ModelPricing(
		model='anthropic/claude-sonnet-4-20250514',
		input_cost_per_token=3.0 / 1_000_000,
		output_cost_per_token=15.0 / 1_000_000,
		cache_read_input_token_cost=0.30 / 1_000_000,
		cache_creation_input_token_cost=3.75 / 1_000_000,
		cache_creation_1h_input_token_cost=7.50 / 1_000_000,
		max_tokens=None,
		max_input_tokens=None,
		max_output_tokens=None,
	)
	token_cost = _make_token_cost(monkeypatch, pricing)

	# prompt_tokens = 3000 total = 2000 regular + 600 cache_read + 200 cache_5m + 200 cache_1h
	usage = ChatInvokeUsage(
		prompt_tokens=3000,
		prompt_cached_tokens=600,
		prompt_cache_creation_tokens=None,
		prompt_cache_creation_5m_tokens=200,
		prompt_cache_creation_1h_tokens=200,
		prompt_image_tokens=None,
		completion_tokens=150,
		total_tokens=3150,
	)

	cost = await token_cost.calculate_cost('anthropic/claude-sonnet-4-20250514', usage)

	assert cost is not None

	# Regular tokens = 3000 - 600 - (200 + 200) = 2000
	expected_new_prompt_cost = 2000 * (3.0 / 1_000_000)
	assert cost.new_prompt_cost == pytest.approx(expected_new_prompt_cost)

	# Cache creation cost: 200 * 3.75/M + 200 * 7.50/M
	expected_cache_creation_cost = 200 * (3.75 / 1_000_000) + 200 * (7.50 / 1_000_000)
	assert cost.prompt_cache_creation_cost == pytest.approx(expected_cache_creation_cost)


@pytest.mark.asyncio
async def test_zero_cache_creation_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
	"""Explicitly zero cache-creation tokens should not affect cost."""
	pricing = ModelPricing(
		model='anthropic/claude-sonnet-4-20250514',
		input_cost_per_token=3.0 / 1_000_000,
		output_cost_per_token=15.0 / 1_000_000,
		cache_read_input_token_cost=0.30 / 1_000_000,
		cache_creation_input_token_cost=3.75 / 1_000_000,
		max_tokens=None,
		max_input_tokens=None,
		max_output_tokens=None,
	)
	token_cost = _make_token_cost(monkeypatch, pricing)

	usage = ChatInvokeUsage(
		prompt_tokens=500,
		prompt_cached_tokens=100,
		prompt_cache_creation_tokens=0,
		prompt_image_tokens=None,
		completion_tokens=50,
		total_tokens=550,
	)

	cost = await token_cost.calculate_cost('anthropic/claude-sonnet-4-20250514', usage)

	assert cost is not None
	# Regular = 500 - 100 - 0 = 400
	assert cost.new_prompt_cost == pytest.approx(400 * (3.0 / 1_000_000))
