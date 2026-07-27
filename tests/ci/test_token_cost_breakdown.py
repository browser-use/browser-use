import pytest

from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import ModelPricing

INPUT_COST = 0.10 / 1_000_000
OUTPUT_COST = 0.20 / 1_000_000
CACHE_READ_COST = 0.02 / 1_000_000


def _usage(prompt_tokens: int, cached: int | None, completion_tokens: int = 40) -> ChatInvokeUsage:
	return ChatInvokeUsage(
		prompt_tokens=prompt_tokens,
		prompt_cached_tokens=cached,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=completion_tokens,
		total_tokens=prompt_tokens + completion_tokens,
	)


@pytest.fixture
def token_cost(monkeypatch: pytest.MonkeyPatch) -> TokenCost:
	async def fake_pricing(model_name: str) -> ModelPricing:
		return ModelPricing(
			model=model_name,
			input_cost_per_token=INPUT_COST,
			output_cost_per_token=OUTPUT_COST,
			cache_read_input_token_cost=CACHE_READ_COST,
			cache_creation_input_token_cost=None,
			max_tokens=None,
			max_input_tokens=None,
			max_output_tokens=None,
		)

	monkeypatch.setattr('browser_use.tokens.service.get_openrouter_model_pricing', fake_pricing)
	cost = TokenCost(include_cost=True)
	cost._initialized = True
	cost._pricing_data = {}
	return cost


async def test_new_prompt_tokens_excludes_cached_tokens(token_cost: TokenCost) -> None:
	"""new_prompt_tokens is the uncached remainder, so the breakdown sums back to prompt_tokens.

	ChatInvokeUsage.prompt_tokens already includes the cached tokens, and
	prompt_read_cached_tokens reports them separately. Reporting the full
	prompt_tokens as "new" counted the cached tokens twice.
	"""
	usage = _usage(prompt_tokens=5000, cached=4900)

	result = await token_cost.calculate_cost('deepseek/deepseek-v4-flash', usage)

	assert result is not None
	assert result.new_prompt_tokens == 100
	assert result.prompt_read_cached_tokens == 4900
	assert result.new_prompt_tokens + (result.prompt_read_cached_tokens or 0) == usage.prompt_tokens


async def test_new_prompt_tokens_matches_its_own_cost(token_cost: TokenCost) -> None:
	"""new_prompt_cost is charged on new_prompt_tokens at the input rate."""
	usage = _usage(prompt_tokens=5000, cached=4900)

	result = await token_cost.calculate_cost('deepseek/deepseek-v4-flash', usage)

	assert result is not None
	assert result.new_prompt_cost == pytest.approx(result.new_prompt_tokens * INPUT_COST)
	assert result.prompt_read_cached_cost == pytest.approx(4900 * CACHE_READ_COST)


async def test_uncached_request_is_unchanged(token_cost: TokenCost) -> None:
	"""With no cache hit every prompt token is new."""
	usage = _usage(prompt_tokens=5000, cached=None)

	result = await token_cost.calculate_cost('deepseek/deepseek-v4-flash', usage)

	assert result is not None
	assert result.new_prompt_tokens == 5000
	assert result.new_prompt_cost == pytest.approx(5000 * INPUT_COST)


async def test_fully_cached_request_reports_no_new_tokens(token_cost: TokenCost) -> None:
	"""A fully cached prompt bills nothing at the input rate."""
	usage = _usage(prompt_tokens=5000, cached=5000)

	result = await token_cost.calculate_cost('deepseek/deepseek-v4-flash', usage)

	assert result is not None
	assert result.new_prompt_tokens == 0
	assert result.new_prompt_cost == pytest.approx(0)
