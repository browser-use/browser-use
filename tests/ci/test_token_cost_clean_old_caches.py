import os
from datetime import datetime
from pathlib import Path

import pytest

from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import CachedPricingData

_PRICING_URL = 'https://example.com/pricing.json'
_OTHER_URL = 'https://other.example.com/pricing.json'


def _write_cache_file(cache_dir: Path, *, source_url: str, name: str, mtime: int) -> Path:
	path = cache_dir / f'{name}.json'
	path.write_text(
		CachedPricingData(
			timestamp=datetime.now(),
			source_url=source_url,
			data={},
		).model_dump_json()
	)
	os.utime(path, (mtime, mtime))
	return path


@pytest.mark.asyncio
async def test_clean_old_caches_keep_count_zero_removes_all_matching(tmp_path: Path) -> None:
	token_cost = TokenCost(include_cost=False, pricing_url=_PRICING_URL)
	token_cost._cache_dir = tmp_path

	files = [_write_cache_file(tmp_path, source_url=_PRICING_URL, name=f'pricing_{i}', mtime=1000 + i) for i in range(3)]
	await token_cost.clean_old_caches(keep_count=0)

	assert all(not path.exists() for path in files)


@pytest.mark.asyncio
async def test_clean_old_caches_keep_count_zero_leaves_other_sources_and_malformed(tmp_path: Path) -> None:
	token_cost = TokenCost(include_cost=False, pricing_url=_PRICING_URL)
	token_cost._cache_dir = tmp_path

	own = _write_cache_file(tmp_path, source_url=_PRICING_URL, name='own', mtime=1000)
	other = _write_cache_file(tmp_path, source_url=_OTHER_URL, name='other', mtime=1001)
	bad = tmp_path / 'bad.json'
	bad.write_text('{not valid json')

	await token_cost.clean_old_caches(keep_count=0)

	assert not own.exists()
	assert other.exists()
	assert bad.exists()


@pytest.mark.asyncio
async def test_clean_old_caches_keep_count_one_retains_newest(tmp_path: Path) -> None:
	token_cost = TokenCost(include_cost=False, pricing_url=_PRICING_URL)
	token_cost._cache_dir = tmp_path

	files = [_write_cache_file(tmp_path, source_url=_PRICING_URL, name=f'pricing_{i}', mtime=1000 + i) for i in range(3)]
	await token_cost.clean_old_caches(keep_count=1)

	assert not files[0].exists()
	assert not files[1].exists()
	assert files[2].exists()
