"""Regression coverage for pricing cache cleanup.

Every pricing refresh writes a new timestamped file into the cache dir;
`clean_old_caches` must be invoked after each write so the directory is
pruned instead of growing unboundedly across long-running sessions.
"""

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path

from pytest_httpserver import HTTPServer

from browser_use.tokens.service import TokenCost


def _write_cache_file(cache_dir: Path, name: str, age_hours: float, source_url: str) -> None:
	content = (
		'{"timestamp": "'
		+ (datetime.now() - timedelta(hours=age_hours)).isoformat()
		+ '", "source_url": "' + source_url + '", "data": {}}'
	)
	target = cache_dir / name
	target.write_text(content, encoding='utf-8')
	# Pin mtime to the intended age so pruning order is unambiguous.
	stat = target.stat()
	os.utime(target, (stat.st_atime, stat.st_mtime - age_hours * 3600))


def _service(tmp_path: Path, pricing_url: str | None = None) -> TokenCost:
	service = TokenCost(include_cost=True, pricing_url=pricing_url)
	service._cache_dir = tmp_path
	return service


def test_clean_old_caches_prunes_by_mtime_not_filename(tmp_path: Path):
	"""Pruning must order by mtime, not by filename: the oldest file here has
	the lexicographically largest name, so a filename-based sort would keep the
	wrong files."""
	service = _service(tmp_path)

	# Ages are deliberately opposite to filename order: pricing_000005 is the
	# OLDEST file (48h) and pricing_000000 is the NEWEST (0h).
	ages = {'pricing_20260101_000005.json': 48, 'pricing_20260101_000004.json': 24, 'pricing_20260101_000003.json': 5}
	DEFAULT_SOURCE = 'https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json'

	for i in range(6):
		name = f'pricing_20260101_00000{i}.json'
		_write_cache_file(tmp_path, name, age_hours=ages.get(name, i), source_url=DEFAULT_SOURCE)
	# Files 000000-000002 are recent (ages 0..2h), 000003-000005 are old (5..48h).

	assert len(list(tmp_path.glob('*.json'))) == 6

	asyncio.run(service.clean_old_caches(keep_count=3))

	remaining = sorted(f.name for f in tmp_path.glob('*.json'))
	assert remaining == [
		'pricing_20260101_000000.json',
		'pricing_20260101_000001.json',
		'pricing_20260101_000002.json',
	], 'must keep the newest-by-mtime files, not the lexicographically smallest names'


def test_fetch_and_cache_invokes_cleanup_end_to_end(httpserver: HTTPServer, tmp_path: Path):
	"""_fetch_and_cache_pricing_data must call clean_old_caches after writing.

	Serves the pricing payload from a local httpserver with the real httpx
	client and the real clean_old_caches, then asserts the final file list:
	also verifies pruning end to end instead of only that a stub was called.
	"""
	httpserver.expect_request('/pricing.json').respond_with_json(
		{'gpt-4o': {'input_cost_per_token': 1e-05, 'output_cost_per_token': 2e-05}}
	)

	# Seed 3 stale cache files from the same source URL so pruning has work to do
	# once the fresh fetch writes a 4th file.
	seeded_url = httpserver.url_for('/pricing.json')
	for i in range(3):
		_write_cache_file(tmp_path, f'pricing_20260101_10000{i}.json', age_hours=10 - i, source_url=seeded_url)

	service = _service(tmp_path, pricing_url=httpserver.url_for('/pricing.json'))

	asyncio.run(service._fetch_and_cache_pricing_data())

	assert service._pricing_data == {'gpt-4o': {'input_cost_per_token': 1e-05, 'output_cost_per_token': 2e-05}}

	files = sorted(f.name for f in tmp_path.glob('*.json'))
	assert len(files) == 3, f'expected pruning to keep 3 files, got {files}'
	# The fresh fetch is newest, so it survives; exactly two of the three seeded files remain.
	fresh = [name for name in files if not name.startswith('pricing_20260101_10000')]
	assert len(fresh) == 1, f'expected the newly written file to survive pruning, got {files}'
