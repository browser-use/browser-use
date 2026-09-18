import asyncio
import re
from datetime import datetime

import pytest

from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost, cost_logger
from browser_use.tokens.views import ModelPricing, ModelUsageStats, UsageSummary


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


@pytest.mark.parametrize('pause_on_lookup', [1, 2], ids=['first-model-pricing', 'second-model-pricing'])
@pytest.mark.parametrize('late_model', ['model-a', 'model-b', 'model-c'])
async def test_logged_usage_summary_excludes_entries_added_during_pricing(
	monkeypatch: pytest.MonkeyPatch, pause_on_lookup: int, late_model: str
) -> None:
	"""Logged totals and per-model costs must use the same usage entries."""
	token_cost = TokenCost(include_cost=True)
	pricing_started = asyncio.Event()
	release_pricing = asyncio.Event()
	pricing_calls = 0
	log_messages: list[str] = []

	async def get_pricing(model_name: str) -> ModelPricing:
		nonlocal pricing_calls
		pricing_calls += 1
		if pricing_calls == pause_on_lookup:
			pricing_started.set()
			await release_pricing.wait()
		return ModelPricing(
			model=model_name,
			input_cost_per_token=0.001,
			output_cost_per_token=0.002,
			cache_read_input_token_cost=None,
			cache_creation_input_token_cost=None,
			max_tokens=None,
			max_input_tokens=None,
			max_output_tokens=None,
		)

	monkeypatch.setattr(token_cost, 'get_model_pricing', get_pricing)
	monkeypatch.setattr(cost_logger, 'debug', log_messages.append)
	token_cost.add_usage('model-a', _usage(10, 5))
	token_cost.add_usage('model-b', _usage(20, 10))

	log_task = asyncio.create_task(token_cost.log_usage_summary())
	try:
		await asyncio.wait_for(pricing_started.wait(), timeout=5)
		token_cost.add_usage(late_model, _usage(100, 50))
	finally:
		release_pricing.set()
		await asyncio.wait_for(log_task, timeout=5)

	lines = [re.sub(r'\x1b\[[0-9;]*m', '', message) for message in log_messages]
	assert len(lines) == 3
	assert 'Total Usage Summary: 45 tokens ($0.0600)' in lines[0]
	assert '30 ($0.0300)' in lines[0]
	assert '15 ($0.0300)' in lines[0]
	assert 'model-a: 15 tokens ($0.0200)' in lines[1]
	assert '10 ($0.0100)' in lines[1]
	assert '5 ($0.0100)' in lines[1]
	assert '1 calls' in lines[1]
	assert '15/call' in lines[1]
	assert 'model-b: 30 tokens ($0.0400)' in lines[2]
	assert '20 ($0.0200)' in lines[2]
	assert '10 ($0.0200)' in lines[2]
	assert '1 calls' in lines[2]
	assert '30/call' in lines[2]
	assert pricing_calls == 2

	# The call excluded from this log is still included in the next summary.
	next_summary = await token_cost.get_usage_summary()
	assert next_summary.entry_count == 3
	assert next_summary.total_tokens == 195
	assert next_summary.total_cost == pytest.approx(0.26)


@pytest.mark.parametrize('include_cost', [False, True], ids=['cost-disabled', 'pricing-unavailable'])
@pytest.mark.parametrize('entry_count', [0, 1, 2])
async def test_logged_usage_summary_without_pricing(
	monkeypatch: pytest.MonkeyPatch, include_cost: bool, entry_count: int
) -> None:
	"""Empty histories stay silent and unpriced usage still logs token counts."""
	monkeypatch.delenv('BROWSER_USE_CALCULATE_COST', raising=False)
	token_cost = TokenCost(include_cost=include_cost)
	log_messages: list[str] = []

	async def get_pricing(model_name: str) -> None:
		assert include_cost
		return None

	monkeypatch.setattr(token_cost, 'get_model_pricing', get_pricing)
	monkeypatch.setattr(cost_logger, 'debug', log_messages.append)
	for index in range(entry_count):
		token_cost.add_usage(f'model-{index}', _usage(10, 5))

	await token_cost.log_usage_summary()

	lines = [re.sub(r'\x1b\[[0-9;]*m', '', message) for message in log_messages]
	assert len(lines) == entry_count + (entry_count > 1)
	assert '$' not in ''.join(lines)
	if entry_count > 1:
		assert 'Total Usage Summary: 30 tokens' in lines[0]
	for index in range(entry_count):
		line = lines[index + (entry_count > 1)]
		assert f'model-{index}: 15 tokens' in line
		assert '1 calls' in line
		assert '15/call' in line


@pytest.mark.parametrize('pause_before_summary', [True, False], ids=['before-snapshot', 'after-snapshot'])
async def test_logged_usage_summary_uses_returned_summary(monkeypatch: pytest.MonkeyPatch, pause_before_summary: bool) -> None:
	"""An override can yield around summary creation without changing log consistency."""
	summary_paused = asyncio.Event()
	release_summary = asyncio.Event()
	pricing_calls = 0
	log_messages: list[str] = []

	class PausingTokenCost(TokenCost):
		async def get_usage_summary(self, model: str | None = None, since: datetime | None = None) -> UsageSummary:
			if pause_before_summary:
				summary_paused.set()
				await release_summary.wait()
			summary = await super().get_usage_summary(model=model, since=since)
			if not pause_before_summary:
				summary_paused.set()
				await release_summary.wait()
			return summary

	token_cost = PausingTokenCost(include_cost=True)

	async def get_pricing(model_name: str) -> ModelPricing:
		nonlocal pricing_calls
		pricing_calls += 1
		return ModelPricing(
			model=model_name,
			input_cost_per_token=0.001,
			output_cost_per_token=0.002,
			cache_read_input_token_cost=None,
			cache_creation_input_token_cost=None,
			max_tokens=None,
			max_input_tokens=None,
			max_output_tokens=None,
		)

	monkeypatch.setattr(token_cost, 'get_model_pricing', get_pricing)
	monkeypatch.setattr(cost_logger, 'debug', log_messages.append)
	token_cost.add_usage('model-a', _usage(10, 5))
	token_cost.add_usage('model-b', _usage(20, 10))

	log_task = asyncio.create_task(token_cost.log_usage_summary())
	try:
		await asyncio.wait_for(summary_paused.wait(), timeout=5)
		token_cost.add_usage('model-a', _usage(100, 50))
	finally:
		release_summary.set()
		await asyncio.wait_for(log_task, timeout=5)

	lines = [re.sub(r'\x1b\[[0-9;]*m', '', message) for message in log_messages]
	assert len(lines) == 3
	if pause_before_summary:
		assert 'Total Usage Summary: 195 tokens ($0.2600)' in lines[0]
		assert 'model-a: 165 tokens ($0.2200)' in lines[1]
		assert '110 ($0.1100)' in lines[1]
		assert '55 ($0.1100)' in lines[1]
		assert '2 calls' in lines[1]
	else:
		assert 'Total Usage Summary: 45 tokens ($0.0600)' in lines[0]
		assert 'model-a: 15 tokens ($0.0200)' in lines[1]
		assert '10 ($0.0100)' in lines[1]
		assert '5 ($0.0100)' in lines[1]
		assert '1 calls' in lines[1]
	assert 'model-b: 30 tokens ($0.0400)' in lines[2]
	assert pricing_calls == (3 if pause_before_summary else 2)


@pytest.mark.parametrize(
	'breakdown',
	[
		{},
		{'prompt_cost': 0.01, 'completion_cost': 0.01},
		{'prompt_cost': 0.01},
		{'completion_cost': 0.02},
		{'prompt_cost': 0.0, 'completion_cost': 0.02},
	],
	ids=['legacy', 'known', 'input-only', 'output-only', 'zero-input'],
)
async def test_logged_usage_summary_uses_serialized_costs(monkeypatch: pytest.MonkeyPatch, breakdown: dict[str, float]) -> None:
	"""Missing cost breakdowns stay unknown, while known zero costs stay zero."""
	stats_data = {
		'model': 'model-a',
		'prompt_tokens': 10,
		'completion_tokens': 5,
		'total_tokens': 15,
		'cost': 0.02,
		'invocations': 1,
		'average_tokens_per_invocation': 15.0,
		**breakdown,
	}
	summary = UsageSummary.model_validate(
		{
			'total_prompt_tokens': 10,
			'total_prompt_cost': 0.01,
			'total_prompt_cached_tokens': 0,
			'total_prompt_cached_cost': 0.0,
			'total_completion_tokens': 5,
			'total_completion_cost': 0.01,
			'total_tokens': 15,
			'total_cost': 0.02,
			'entry_count': 1,
			'by_model': {'model-a': stats_data},
		}
	)
	restored_summary = UsageSummary.model_validate_json(summary.model_dump_json())
	assert restored_summary == summary
	stats = restored_summary.by_model['model-a']
	assert stats.prompt_cost == breakdown.get('prompt_cost')
	assert stats.completion_cost == breakdown.get('completion_cost')

	token_cost = TokenCost(include_cost=True)
	token_cost.add_usage('model-a', _usage(10, 5))
	log_messages: list[str] = []

	async def get_summary() -> UsageSummary:
		return restored_summary

	async def unexpected_calculation(*args, **kwargs):
		pytest.fail('Logging must not recalculate costs from usage history')

	monkeypatch.setattr(token_cost, 'get_usage_summary', get_summary)
	monkeypatch.setattr(token_cost, 'calculate_cost', unexpected_calculation)
	monkeypatch.setattr(cost_logger, 'debug', log_messages.append)
	await token_cost.log_usage_summary()

	assert len(log_messages) == 1
	line = re.sub(r'\x1b\[[0-9;]*m', '', log_messages[0])
	assert 'model-a: 15 tokens ($0.0200)' in line
	for field, tokens in [('prompt_cost', 10), ('completion_cost', 5)]:
		if field in breakdown:
			assert f'{tokens} (${breakdown[field]:.4f})' in line
		else:
			assert f'{tokens} ($' not in line


@pytest.mark.parametrize('priced', [False, True], ids=['unknown', 'free'])
async def test_usage_summary_distinguishes_unknown_and_zero_costs(monkeypatch: pytest.MonkeyPatch, priced: bool) -> None:
	token_cost = TokenCost(include_cost=True)

	async def get_pricing(model_name: str) -> ModelPricing | None:
		if not priced:
			return None
		return ModelPricing(
			model=model_name,
			input_cost_per_token=0.0,
			output_cost_per_token=0.0,
			cache_read_input_token_cost=None,
			cache_creation_input_token_cost=None,
			max_tokens=None,
			max_input_tokens=None,
			max_output_tokens=None,
		)

	monkeypatch.setattr(token_cost, 'get_model_pricing', get_pricing)
	token_cost.add_usage('model-a', _usage(10, 5))
	summary = await token_cost.get_usage_summary()
	stats = summary.by_model['model-a']
	assert stats.cost == 0.0
	assert stats.prompt_cost == (0.0 if priced else None)
	assert stats.completion_cost == (0.0 if priced else None)
	assert ModelUsageStats.model_validate_json(stats.model_dump_json()) == stats


@pytest.mark.parametrize('unpriced_entry', [0, 1])
async def test_usage_summary_accumulates_available_costs(monkeypatch: pytest.MonkeyPatch, unpriced_entry: int) -> None:
	"""Mixed pricing retains all tokens and sums only the available costs."""
	token_cost = TokenCost(include_cost=True)
	pricing_calls = 0
	log_messages: list[str] = []

	async def get_pricing(model_name: str) -> ModelPricing | None:
		nonlocal pricing_calls
		entry_index = pricing_calls
		pricing_calls += 1
		if entry_index == unpriced_entry:
			return None
		return ModelPricing(
			model=model_name,
			input_cost_per_token=0.001,
			output_cost_per_token=0.002,
			cache_read_input_token_cost=None,
			cache_creation_input_token_cost=None,
			max_tokens=None,
			max_input_tokens=None,
			max_output_tokens=None,
		)

	monkeypatch.setattr(token_cost, 'get_model_pricing', get_pricing)
	monkeypatch.setattr(cost_logger, 'debug', log_messages.append)
	token_cost.add_usage('model-a', _usage(10, 5))
	token_cost.add_usage('model-a', _usage(20, 10))
	token_cost.add_usage('model-b', _usage(30, 15))
	summary = await token_cost.get_usage_summary()
	expected_a_cost = 0.04 if unpriced_entry == 0 else 0.02
	stats = summary.by_model['model-a']
	assert stats.total_tokens == 45
	assert stats.invocations == 2
	assert stats.cost == pytest.approx(expected_a_cost)
	assert stats.prompt_cost == pytest.approx(expected_a_cost / 2)
	assert stats.completion_cost == pytest.approx(expected_a_cost / 2)
	assert summary.total_tokens == 90
	assert summary.total_cost == pytest.approx(expected_a_cost + 0.06)
	assert summary.total_prompt_cost == pytest.approx(sum(item.prompt_cost or 0.0 for item in summary.by_model.values()))
	assert summary.total_completion_cost == pytest.approx(sum(item.completion_cost or 0.0 for item in summary.by_model.values()))
	assert pricing_calls == 3

	pricing_calls = 0
	await token_cost.log_usage_summary()
	assert pricing_calls == 3
	lines = [re.sub(r'\x1b\[[0-9;]*m', '', message) for message in log_messages]
	assert len(lines) == 3
	assert f'Total Usage Summary: 90 tokens (${expected_a_cost + 0.06:.4f})' in lines[0]
	assert f'model-a: 45 tokens (${expected_a_cost:.4f})' in lines[1]
	assert f'30 (${expected_a_cost / 2:.4f})' in lines[1]
	assert f'15 (${expected_a_cost / 2:.4f})' in lines[1]
	assert 'model-b: 45 tokens ($0.0600)' in lines[2]
