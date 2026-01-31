"""Tests for PR 5: Error recovery and multi-page aggregation."""

from browser_use.tools.extraction.aggregator import ExtractionAggregator
from browser_use.tools.extraction.views import ExtractionResult


class TestExtractionAggregator:
	def test_add_list_results(self):
		agg = ExtractionAggregator()
		eid = 'test-123'

		result1 = ExtractionResult(data=[{'name': 'A', 'price': 10}, {'name': 'B', 'price': 20}])
		result2 = ExtractionResult(data=[{'name': 'C', 'price': 30}, {'name': 'D', 'price': 40}])

		agg.add(eid, result1)
		agg.add(eid, result2)

		aggregated = agg.aggregate(eid)
		assert aggregated.data is not None
		assert len(aggregated.data) == 4

	def test_deduplication(self):
		agg = ExtractionAggregator()
		eid = 'dedup-test'

		result1 = ExtractionResult(data=[{'name': 'A', 'price': 10}, {'name': 'B', 'price': 20}])
		# Second page has one duplicate
		result2 = ExtractionResult(data=[{'name': 'B', 'price': 20}, {'name': 'C', 'price': 30}])

		agg.add(eid, result1)
		agg.add(eid, result2)

		aggregated = agg.aggregate(eid)
		assert len(aggregated.data) == 3  # A, B, C — B deduplicated

	def test_dict_result_with_list_field(self):
		agg = ExtractionAggregator()
		eid = 'dict-test'

		result1 = ExtractionResult(data={'products': [{'name': 'A'}, {'name': 'B'}]})
		result2 = ExtractionResult(data={'products': [{'name': 'C'}, {'name': 'D'}]})

		agg.add(eid, result1)
		agg.add(eid, result2)

		aggregated = agg.aggregate(eid)
		# Both dicts' list items extracted and merged
		assert len(aggregated.data) == 4

	def test_dict_result_with_mixed_list_and_non_list_fields(self):
		"""Dict with both list and non-list fields should only extract list items."""
		agg = ExtractionAggregator()
		eid = 'mixed-dict'

		result1 = ExtractionResult(data={'products': [{'name': 'A'}], 'total': 100, 'page': 1})
		result2 = ExtractionResult(data={'products': [{'name': 'B'}], 'total': 100, 'page': 2})

		agg.add(eid, result1)
		agg.add(eid, result2)

		aggregated = agg.aggregate(eid)
		# Only list items extracted — non-list fields (total, page) ignored
		assert len(aggregated.data) == 2
		names = {item['name'] for item in aggregated.data}
		assert names == {'A', 'B'}

	def test_summary(self):
		agg = ExtractionAggregator()
		eid = 'summary-test'

		agg.add(eid, ExtractionResult(data=[{'id': 1}, {'id': 2}]))
		agg.add(eid, ExtractionResult(data=[{'id': 3}]))

		summary = agg.summary(eid)
		assert '3 unique items' in summary
		assert '2 pages' in summary
		assert eid in summary

	def test_aggregate_empty(self):
		agg = ExtractionAggregator()
		aggregated = agg.aggregate('nonexistent')
		assert aggregated.data == []
		assert aggregated.content_stats['total_items'] == 0
		assert aggregated.content_stats['pages_aggregated'] == 0

	def test_has_data(self):
		agg = ExtractionAggregator()
		eid = 'check-test'
		assert not agg.has_data(eid)

		agg.add(eid, ExtractionResult(data=[{'x': 1}]))
		assert agg.has_data(eid)

	def test_null_data_ignored(self):
		agg = ExtractionAggregator()
		eid = 'null-test'

		agg.add(eid, ExtractionResult(data=None))
		assert not agg.has_data(eid)
		# But page count should still increase
		aggregated = agg.aggregate(eid)
		assert aggregated.content_stats['pages_aggregated'] == 1

	def test_clear_specific(self):
		agg = ExtractionAggregator()
		agg.add('a', ExtractionResult(data=[1, 2]))
		agg.add('b', ExtractionResult(data=[3, 4]))

		agg.clear('a')
		assert not agg.has_data('a')
		assert agg.has_data('b')

	def test_clear_all(self):
		agg = ExtractionAggregator()
		agg.add('a', ExtractionResult(data=[1]))
		agg.add('b', ExtractionResult(data=[2]))

		agg.clear()
		assert not agg.has_data('a')
		assert not agg.has_data('b')

	def test_three_page_aggregation(self):
		"""Simulate extracting products from 3 pages of results."""
		agg = ExtractionAggregator()
		eid = 'pagination-test'

		# Page 1: products 1-5
		page1 = ExtractionResult(data=[{'id': i, 'name': f'Product {i}'} for i in range(1, 6)])
		# Page 2: products 6-10
		page2 = ExtractionResult(data=[{'id': i, 'name': f'Product {i}'} for i in range(6, 11)])
		# Page 3: products 11-15 with overlap (product 10 appears again)
		page3 = ExtractionResult(data=[{'id': i, 'name': f'Product {i}'} for i in range(10, 16)])

		agg.add(eid, page1)
		agg.add(eid, page2)
		agg.add(eid, page3)

		aggregated = agg.aggregate(eid)
		# Should have 15 unique products (product 10 deduplicated)
		assert len(aggregated.data) == 15
		assert aggregated.content_stats['pages_aggregated'] == 3

		# Summary should reflect the counts
		summary = agg.summary(eid)
		assert '15 unique items' in summary
		assert '3 pages' in summary

	def test_primitive_items(self):
		"""Aggregator handles simple primitive lists."""
		agg = ExtractionAggregator()
		eid = 'primitives'

		agg.add(eid, ExtractionResult(data=[1, 2, 3]))
		agg.add(eid, ExtractionResult(data=[3, 4, 5]))  # 3 is duplicate

		aggregated = agg.aggregate(eid)
		assert sorted(aggregated.data) == [1, 2, 3, 4, 5]

	def test_single_page_summary(self):
		agg = ExtractionAggregator()
		eid = 'single'
		agg.add(eid, ExtractionResult(data=[{'x': 1}]))

		summary = agg.summary(eid)
		assert '1 page' in summary  # singular
		assert '1 unique item' in summary
