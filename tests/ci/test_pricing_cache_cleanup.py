"""Regression coverage for pricing cache cleanup.

Every pricing refresh writes a new timestamped file into the cache dir;
`clean_old_caches` must be invoked after each write so the directory is
pruned instead of growing unboundedly across long-running sessions.
"""

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path

from browser_use.tokens.service import TokenCost


def _write_cache_file(cache_dir: Path, name: str, age_hours: float) -> None:
	content = (
		'{"timestamp": "'
		+ (datetime.now() - timedelta(hours=age_hours)).isoformat()
		+ '", "source_url": "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json", "data": {}}'
	)
	target = cache_dir / name
	target.write_text(content, encoding='utf-8')
	# mtime ordering must match the age so pruning keeps the newest
	stat = target.stat()
	os.utime(target, (stat.st_atime, stat.st_mtime - age_hours * 3600))


def _service(tmp_path: Path) -> TokenCost:
	service = TokenCost(include_cost=True)
	service._cache_dir = tmp_path
	return service


def test_clean_old_caches_prunes_to_keep_count(tmp_path: Path):
	service = _service(tmp_path)

	for i in range(6):
		_write_cache_file(tmp_path, f'pricing_20260101_00000{i}.json', age_hours=6 - i)

	assert len(list(tmp_path.glob('*.json'))) == 6

	asyncio.run(service.clean_old_caches(keep_count=3))

	remaining = sorted(f.name for f in tmp_path.glob('*.json'))
	assert remaining == [
		'pricing_20260101_000003.json',
		'pricing_20260101_000004.json',
		'pricing_20260101_000005.json',
	]


def test_fetch_and_cache_invokes_cleanup(monkeypatch, tmp_path: Path):
	"""_fetch_and_cache_pricing_data must call clean_old_caches after writing."""
	service = _service(tmp_path)

	calls: list[int] = []

	async def fake_clean(keep_count: int = 3) -> None:
		calls.append(keep_count)

	monkeypatch.setattr(service, 'clean_old_caches', fake_clean)

	class _FakeResponse:
		def raise_for_status(self) -> None: ...

		def json(self) -> dict:
			return {'gpt-4o': {'input_cost_per_token': 1e-05, 'output_cost_per_token': 2e-05}}

	class _FakeClient:
		def __init__(self, *args, **kwargs): ...

		async def __aenter__(self):
			return self

		async def __aexit__(self, *args):
			return False

		async def get(self, url, timeout):
			return _FakeResponse()

	import httpx

	monkeypatch.setattr(httpx, 'AsyncClient', _FakeClient)

	asyncio.run(service._fetch_and_cache_pricing_data())

	assert calls == [3], 'clean_old_caches must be invoked exactly once after a successful cache write'
	assert service._pricing_data == {'gpt-4o': {'input_cost_per_token': 1e-05, 'output_cost_per_token': 2e-05}}
	assert len(list(tmp_path.glob('pricing_*.json'))) == 1
