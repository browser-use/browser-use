"""Regression test: clean_old_caches(keep_count=0) must remove every cache file.

The slice `own_files[:-keep_count]` becomes an empty slice when `keep_count` is 0, so a caller that
asks for zero retained caches kept all of them instead.
"""

import os
from datetime import datetime
from pathlib import Path

from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import CachedPricingData


def _write_cache(cache_dir: Path, name: str, source_url: str, mtime: int) -> Path:
	cache_file = cache_dir / name
	cached = CachedPricingData(timestamp=datetime.now(), source_url=source_url, data={'model': {}})
	cache_file.write_text(cached.model_dump_json())
	os.utime(cache_file, (mtime, mtime))
	return cache_file


def _service(tmp_path: Path) -> TokenCost:
	service = TokenCost(include_cost=True, pricing_url='https://example.test/pricing.json')
	service._cache_dir = tmp_path
	return service


async def test_clean_old_caches_with_zero_removes_all_matching_files(tmp_path: Path) -> None:
	service = _service(tmp_path)
	for index in range(3):
		_write_cache(tmp_path, f'pricing_0{index}.json', service.pricing_url, 1_000 + index)

	await service.clean_old_caches(keep_count=0)

	assert list(tmp_path.glob('*.json')) == []


async def test_clean_old_caches_with_positive_count_keeps_newest(tmp_path: Path) -> None:
	service = _service(tmp_path)
	for index in range(3):
		_write_cache(tmp_path, f'pricing_0{index}.json', service.pricing_url, 1_000 + index)

	await service.clean_old_caches(keep_count=2)

	remaining = sorted(path.name for path in tmp_path.glob('*.json'))
	assert remaining == ['pricing_01.json', 'pricing_02.json']


async def test_clean_old_caches_ignores_files_from_other_sources(tmp_path: Path) -> None:
	service = _service(tmp_path)
	_write_cache(tmp_path, 'pricing_own.json', service.pricing_url, 1_000)
	_write_cache(tmp_path, 'pricing_other.json', 'https://other.test/pricing.json', 1_001)

	await service.clean_old_caches(keep_count=0)

	remaining = sorted(path.name for path in tmp_path.glob('*.json'))
	assert remaining == ['pricing_other.json']
