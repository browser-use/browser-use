import os
from datetime import datetime
from pathlib import Path

import pytest

from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import CachedPricingData


@pytest.mark.parametrize('keep_count', [0, 1, 3])
async def test_cache_cleanup_keeps_requested_count_for_own_source(tmp_path: Path, keep_count: int) -> None:
	token_cost = TokenCost(pricing_url='https://example.com/pricing.json')
	token_cost._cache_dir = tmp_path
	for index in range(3):
		cache = tmp_path / f'pricing_{index}.json'
		cache.write_text(
			CachedPricingData(timestamp=datetime.now(), source_url=token_cost.pricing_url, data={}).model_dump_json()
		)
		os.utime(cache, (index + 1, index + 1))
	foreign = tmp_path / 'foreign.json'
	foreign.write_text(
		CachedPricingData(timestamp=datetime.now(), source_url='https://other.example/pricing.json', data={}).model_dump_json()
	)
	corrupt = tmp_path / 'corrupt.json'
	corrupt.write_text('not JSON')

	await token_cost.clean_old_caches(keep_count=keep_count)

	assert sorted(path.name for path in tmp_path.glob('pricing_*.json')) == [
		f'pricing_{index}.json' for index in range(3 - keep_count, 3)
	]
	assert foreign.exists()
	assert corrupt.read_text() == 'not JSON'
