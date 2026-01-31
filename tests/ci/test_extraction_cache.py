"""Tests for PR 4: Extraction strategy cache."""

import pytest

from browser_use.tools.extraction.cache import ExtractionCache
from browser_use.tools.extraction.views import ExtractionStrategy


class TestExtractionCache:
	def test_register_and_get(self):
		cache = ExtractionCache()
		strategy = ExtractionStrategy(
			url_pattern='https://example.com/products/*',
			js_script='(function(){ return []; })()',
			query_template='Get products',
		)
		cache.register(strategy)

		retrieved = cache.get(strategy.id)
		assert retrieved is not None
		assert retrieved.id == strategy.id
		assert retrieved.js_script == strategy.js_script

	def test_get_nonexistent(self):
		cache = ExtractionCache()
		assert cache.get('nonexistent-id') is None

	def test_url_pattern_matching(self):
		cache = ExtractionCache()
		strategy = ExtractionStrategy(
			url_pattern='https://example.com/products/*',
			js_script='(function(){ return []; })()',
			query_template='Get products',
		)
		cache.register(strategy)

		# Should match
		found = cache.find_matching('https://example.com/products/page-2')
		assert found is not None
		assert found.id == strategy.id

		# Should not match
		not_found = cache.find_matching('https://other.com/products/page-1')
		assert not_found is None

	def test_url_matching_glob_wildcards(self):
		cache = ExtractionCache()
		strategy = ExtractionStrategy(
			url_pattern='https://shop.example.com/*/items',
			js_script='(function(){ return []; })()',
			query_template='Get items',
		)
		cache.register(strategy)

		assert cache.find_matching('https://shop.example.com/category-a/items') is not None
		assert cache.find_matching('https://shop.example.com/category-b/items') is not None
		assert cache.find_matching('https://shop.example.com/other/path') is None

	def test_best_strategy_by_success_count(self):
		cache = ExtractionCache()
		strategy1 = ExtractionStrategy(
			url_pattern='https://example.com/*',
			js_script='script1',
			query_template='query1',
			success_count=5,
		)
		strategy2 = ExtractionStrategy(
			url_pattern='https://example.com/*',
			js_script='script2',
			query_template='query2',
			success_count=10,
		)
		cache.register(strategy1)
		cache.register(strategy2)

		best = cache.find_matching('https://example.com/page')
		assert best is not None
		assert best.id == strategy2.id
		assert best.success_count == 10

	def test_record_success_failure(self):
		cache = ExtractionCache()
		strategy = ExtractionStrategy(
			url_pattern='https://example.com/*',
			js_script='script',
			query_template='query',
		)
		cache.register(strategy)

		assert strategy.success_count == 0
		assert strategy.failure_count == 0

		cache.record_success(strategy.id)
		cache.record_success(strategy.id)
		assert strategy.success_count == 2

		cache.record_failure(strategy.id)
		assert strategy.failure_count == 1

	def test_remove(self):
		cache = ExtractionCache()
		strategy = ExtractionStrategy(
			url_pattern='https://example.com/*',
			js_script='script',
			query_template='query',
		)
		cache.register(strategy)
		assert cache.size == 1

		cache.remove(strategy.id)
		assert cache.size == 0
		assert cache.get(strategy.id) is None

	def test_clear(self):
		cache = ExtractionCache()
		for i in range(5):
			cache.register(
				ExtractionStrategy(
					url_pattern=f'https://example{i}.com/*',
					js_script=f'script{i}',
					query_template=f'query{i}',
				)
			)
		assert cache.size == 5

		cache.clear()
		assert cache.size == 0

	def test_strategy_without_js_not_matched(self):
		"""Strategies without js_script should not be returned by find_matching."""
		cache = ExtractionCache()
		strategy = ExtractionStrategy(
			url_pattern='https://example.com/*',
			js_script=None,
			query_template='query',
		)
		cache.register(strategy)

		found = cache.find_matching('https://example.com/page')
		assert found is None

	def test_strategy_without_url_pattern_not_matched(self):
		cache = ExtractionCache()
		strategy = ExtractionStrategy(
			url_pattern='',
			js_script='script',
			query_template='query',
		)
		cache.register(strategy)

		found = cache.find_matching('https://example.com/page')
		assert found is None


class TestExtractionStrategy:
	def test_default_id_generated(self):
		s1 = ExtractionStrategy(url_pattern='*', query_template='q')
		s2 = ExtractionStrategy(url_pattern='*', query_template='q')
		assert s1.id != s2.id
		assert len(s1.id) > 0

	def test_fields(self):
		strategy = ExtractionStrategy(
			url_pattern='https://example.com/*',
			js_script='(function(){ return {}; })()',
			css_selector='table',
			output_schema={'type': 'object', 'properties': {'items': {'type': 'array'}}},
			query_template='Get items',
			success_count=3,
			failure_count=1,
		)
		assert strategy.url_pattern == 'https://example.com/*'
		assert strategy.css_selector == 'table'
		assert strategy.success_count == 3
		assert strategy.failure_count == 1
