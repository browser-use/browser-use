import asyncio
from pathlib import Path

from pytest_httpserver import HTTPServer

from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import CachedPricingData


async def test_concurrent_price_sources_keep_independent_cache_files(httpserver: HTTPServer, tmp_path: Path) -> None:
	"""Concurrent refreshes must preserve every source for subsequent offline loads."""
	costs = []
	for index in range(8):
		path = f'/pricing/{index}'
		httpserver.expect_request(path).respond_with_json({f'model-{index}': {'input_cost_per_token': index + 1}})
		cost = TokenCost(include_cost=True, pricing_url=httpserver.url_for(path))
		cost._cache_dir = tmp_path
		costs.append(cost)

	await asyncio.gather(*(cost._fetch_and_cache_pricing_data() for cost in costs))

	cached_sources = {CachedPricingData.model_validate_json(path.read_text()).source_url for path in tmp_path.glob('*.json')}
	assert cached_sources == {cost.pricing_url for cost in costs}

	# No further HTTP requests are allowed: new instances must load their own disk cache.
	httpserver.clear()
	for index, cost in enumerate(costs):
		reloaded = TokenCost(include_cost=True, pricing_url=cost.pricing_url)
		reloaded._cache_dir = tmp_path
		await reloaded.initialize()
		assert reloaded._pricing_data == {f'model-{index}': {'input_cost_per_token': index + 1}}
	httpserver.check_assertions()
