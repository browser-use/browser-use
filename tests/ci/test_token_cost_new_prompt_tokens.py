"""Regression test for TokenCost.calculate_cost token accounting.

`new_prompt_tokens` is paired with `new_prompt_cost`, which is priced on the
*uncached* prompt tokens (`prompt_tokens - prompt_cached_tokens`). The field was
assigned the full `prompt_tokens` total (which includes cached tokens), so the
reported token count and its cost described different quantities.
"""

import pytest

from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import ModelPricing


def _pricing() -> ModelPricing:
	return ModelPricing(
		model='test-model',
		input_cost_per_token=1e-6,
		output_cost_per_token=2e-6,
		cache_read_input_token_cost=1e-7,
		cache_creation_input_token_cost=None,
		max_tokens=None,
		max_input_tokens=None,
		max_output_tokens=None,
	)


async def test_new_prompt_tokens_excludes_cached(monkeypatch: pytest.MonkeyPatch):
	tc = TokenCost(include_cost=True)

	async def fake_get_model_pricing(model_name: str) -> ModelPricing:
		return _pricing()

	monkeypatch.setattr(tc, 'get_model_pricing', fake_get_model_pricing)

	usage = ChatInvokeUsage(
		prompt_tokens=1000,
		prompt_cached_tokens=400,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=100,
		total_tokens=1100,
	)

	cost = await tc.calculate_cost('test-model', usage)
	assert cost is not None

	# 1000 total - 400 cached = 600 uncached ("new") tokens
	assert cost.new_prompt_tokens == 600
	# Cost is priced on the same 600 tokens.
	assert cost.new_prompt_cost == pytest.approx(600 * 1e-6)
	# Cached tokens are reported separately and unchanged.
	assert cost.prompt_read_cached_tokens == 400
