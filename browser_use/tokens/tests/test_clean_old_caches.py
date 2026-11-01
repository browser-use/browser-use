"""Tests for TokenCost.clean_old_caches keep_count semantics."""

import os
from datetime import datetime
from pathlib import Path

import pytest

from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import CachedPricingData


@pytest.fixture
def token_cost_with_cache(tmp_path):
	"""Create a TokenCost instance with a temp cache directory."""
	tc = TokenCost(include_cost=False, pricing_url='https://example.com/pricing.json')
	tc._cache_dir = tmp_path
	tc._cache_dir.mkdir(parents=True, exist_ok=True)
	return tc


def _make_cache_file(cache_dir: Path, index: int) -> Path:
	"""Create a cache file with a given modification time."""
	f = cache_dir / f'cache_{index}.json'
	cached = CachedPricingData(
		timestamp=datetime.now(),
		source_url='https://example.com/pricing.json',
		data={'model': f'model_{index}'},
	)
	f.write_text(cached.model_dump_json())
	os.utime(f, (1000 + index, 1000 + index))
	return f


@pytest.mark.asyncio
async def test_clean_old_caches_keep_count_zero_removes_all(token_cost_with_cache):
	"""keep_count=0 should remove ALL matching cache files."""
	tc = token_cost_with_cache
	cache_dir = tc._cache_dir

	files = [_make_cache_file(cache_dir, i) for i in range(5)]
	assert all(f.exists() for f in files)

	await tc.clean_old_caches(keep_count=0)

	assert all(not f.exists() for f in files), 'keep_count=0 should remove all files'


@pytest.mark.asyncio
async def test_clean_old_caches_keep_count_positive_keeps_recent(token_cost_with_cache):
	"""keep_count=N should keep only the N most recent files."""
	tc = token_cost_with_cache
	cache_dir = tc._cache_dir

	files = [_make_cache_file(cache_dir, i) for i in range(5)]
	await tc.clean_old_caches(keep_count=2)

	remaining = [f for f in files if f.exists()]
	assert len(remaining) == 2, f'Expected 2 remaining, got {len(remaining)}'
	assert files[-1] in remaining
	assert files[-2] in remaining


@pytest.mark.asyncio
async def test_clean_old_caches_keep_count_greater_than_files(token_cost_with_cache):
	"""keep_count larger than number of files should remove nothing."""
	tc = token_cost_with_cache
	cache_dir = tc._cache_dir

	files = [_make_cache_file(cache_dir, i) for i in range(3)]
	await tc.clean_old_caches(keep_count=10)

	assert all(f.exists() for f in files), 'No files should be removed when keep_count > file count'


@pytest.mark.asyncio
async def test_clean_old_caches_keep_count_one(token_cost_with_cache):
	"""keep_count=1 should keep only the single most recent file."""
	tc = token_cost_with_cache
	cache_dir = tc._cache_dir

	files = [_make_cache_file(cache_dir, i) for i in range(4)]
	await tc.clean_old_caches(keep_count=1)

	remaining = [f for f in files if f.exists()]
	assert len(remaining) == 1
	assert files[-1] in remaining
