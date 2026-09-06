import asyncio
from datetime import datetime

import pytest

from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import ModelPricing


def _usage(prompt_tokens: int, completion_tokens: int) -> ChatInvokeUsage:
	return ChatInvokeUsage(
		prompt_tokens=prompt_tokens,
		completion_tokens=completion_tokens,
		total_tokens=prompt_tokens + completion_tokens,
		prompt_cached_tokens=None,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
	)


@pytest.mark.parametrize('model_filter', [None, 'model-a'])
@pytest.mark.parametrize('since', [None, datetime.min])
async def test_usage_summary_excludes_entries_added_during_pricing(
	monkeypatch: pytest.MonkeyPatch, model_filter: str | None, since: datetime | None
) -> None:
	"""A summary must count and price the same entries while new calls finish."""
	token_cost = TokenCost(include_cost=True)
	pricing_started = asyncio.Event()
	release_pricing = asyncio.Event()

	async def get_pricing(model_name: str) -> ModelPricing:
		pricing_started.set()
		await release_pricing.wait()
		return ModelPricing(
			model=model_name,
			input_cost_per_token=0.000001,
			output_cost_per_token=0.000002,
			cache_read_input_token_cost=None,
			cache_creation_input_token_cost=None,
			max_tokens=None,
			max_input_tokens=None,
			max_output_tokens=None,
		)

	monkeypatch.setattr(token_cost, 'get_model_pricing', get_pricing)
	token_cost.add_usage('model-a', _usage(10, 5))
	token_cost.add_usage('model-b', _usage(20, 10))

	summary_task = asyncio.create_task(token_cost.get_usage_summary(model=model_filter, since=since))
	try:
		await asyncio.wait_for(pricing_started.wait(), timeout=5)
		token_cost.add_usage('model-a', _usage(100, 50))
	finally:
		release_pricing.set()
		if not summary_task.done():
			await asyncio.wait_for(summary_task, timeout=5)
	summary = summary_task.result()

	assert summary.entry_count == (1 if model_filter else 2)
	assert summary.total_tokens == (15 if model_filter else 45)
	assert summary.total_cost == pytest.approx(0.00002 if model_filter else 0.00006)
	assert summary.total_tokens == sum(stats.total_tokens for stats in summary.by_model.values())
	assert summary.entry_count == sum(stats.invocations for stats in summary.by_model.values())
	assert summary.total_cost == pytest.approx(sum(stats.cost for stats in summary.by_model.values()))

	# The concurrently completed call remains available to subsequent summaries.
	next_summary = await token_cost.get_usage_summary(model=model_filter, since=since)
	assert next_summary.entry_count == summary.entry_count + 1
	assert next_summary.total_tokens == summary.total_tokens + 150
	assert next_summary.total_cost == pytest.approx(summary.total_cost + 0.0002)
