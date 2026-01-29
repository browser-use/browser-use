"""Tests for markdown extractor preprocessing."""

import pytest

from browser_use.dom.markdown_extractor import _preprocess_markdown_content, smart_truncate
from browser_use.dom.content_filter import is_semantic_data_attr, is_spa_state_json


class TestPreprocessMarkdownContent:
	"""Tests for _preprocess_markdown_content function."""

	def test_preserves_short_lines(self):
		"""Short lines (1-2 chars) should be preserved, not removed."""
		content = '# Items\na\nb\nc\nOK\nNo'
		filtered, stats = _preprocess_markdown_content(content)

		assert 'a' in filtered.split('\n')
		assert 'b' in filtered.split('\n')
		assert 'c' in filtered.split('\n')
		assert 'OK' in filtered.split('\n')
		assert 'No' in filtered.split('\n')

	def test_preserves_single_digit_numbers(self):
		"""Single digit page numbers should be preserved."""
		content = 'Page navigation:\n1\n2\n3\n10'
		filtered, stats = _preprocess_markdown_content(content)

		lines = filtered.split('\n')
		assert '1' in lines
		assert '2' in lines
		assert '3' in lines
		assert '10' in lines

	def test_preserves_markdown_list_items(self):
		"""Markdown list items with short content should be preserved."""
		content = 'Shopping list:\n- a\n- b\n- OK\n- No'
		filtered, stats = _preprocess_markdown_content(content)

		assert '- a' in filtered
		assert '- b' in filtered
		assert '- OK' in filtered
		assert '- No' in filtered

	def test_preserves_state_codes(self):
		"""Two-letter state codes should be preserved."""
		content = 'States:\nCA\nNY\nTX'
		filtered, stats = _preprocess_markdown_content(content)

		lines = filtered.split('\n')
		assert 'CA' in lines
		assert 'NY' in lines
		assert 'TX' in lines

	def test_removes_excessive_empty_lines(self):
		"""Excessive empty lines should be compressed."""
		content = 'Header\n\n\n\n\nContent'
		filtered, stats = _preprocess_markdown_content(content)

		# Should not have more than 2 consecutive empty lines
		assert '\n\n\n\n' not in filtered

	def test_removes_spa_framework_state_json(self):
		"""SPA framework state JSON should be removed."""
		# React-style state with $$typeof
		react_state = '{"$$typeof": "Symbol(react.element)", "props": {"children": []}}'
		content = f'Header\n{react_state}\nFooter'
		filtered, stats = _preprocess_markdown_content(content)

		assert react_state not in filtered
		assert 'Header' in filtered
		assert 'Footer' in filtered

	def test_preserves_legitimate_json_data(self):
		"""Legitimate JSON data (product info, etc.) should be preserved."""
		# This is product data, not framework state
		product_json = '{"name": "iPhone 15", "price": 999, "color": "blue"}'
		content = f'Header\n{product_json}\nFooter'
		filtered, stats = _preprocess_markdown_content(content)

		# Legitimate data JSON should be preserved
		assert product_json in filtered

	def test_removes_nextjs_page_props(self):
		"""Next.js __NEXT_DATA__ patterns should be removed."""
		nextjs_state = '{"__NEXT_DATA__": {"props": {"pageProps": {}}, "page": "/"}}'
		content = f'Header\n{nextjs_state}\nFooter'
		filtered, stats = _preprocess_markdown_content(content)

		assert nextjs_state not in filtered
		assert 'Header' in filtered
		assert 'Footer' in filtered

	def test_compresses_multiple_newlines(self):
		"""4+ consecutive newlines should be compressed to max_newlines."""
		content = 'Header\n\n\n\n\nFooter'
		filtered, stats = _preprocess_markdown_content(content, max_newlines=2)

		# Should not have 4+ newlines
		assert '\n\n\n\n' not in filtered
		assert 'Header' in filtered
		assert 'Footer' in filtered

	def test_returns_stats_dict(self):
		"""Should return stats dictionary with filtering info."""
		content = 'Header\n\n\n\n\nFooter'
		filtered, stats = _preprocess_markdown_content(content)

		assert isinstance(stats, dict)
		assert 'chars_filtered' in stats
		assert 'json_blobs_removed' in stats
		assert 'whitespace_normalized' in stats

	def test_strips_result(self):
		"""Result should be stripped of leading/trailing whitespace."""
		content = '  \n\nContent\n\n  '
		filtered, stats = _preprocess_markdown_content(content)

		assert not filtered.startswith(' ')
		assert not filtered.startswith('\n')
		assert not filtered.endswith(' ')
		assert not filtered.endswith('\n')


class TestSmartTruncate:
	"""Tests for smart_truncate function."""

	def test_no_truncation_needed(self):
		"""Content under limit should not be truncated."""
		content = 'Short content'
		result, info = smart_truncate(content, max_chars=1000)

		assert result == content
		assert info['truncated'] is False

	def test_truncates_at_paragraph_boundary(self):
		"""Should prefer truncating at paragraph boundaries."""
		content = 'First paragraph.\n\nSecond paragraph.\n\nThird paragraph that goes on for a while.'
		result, info = smart_truncate(content, max_chars=50)

		assert info['truncated'] is True
		assert info['truncation_method'] in ('paragraph_break', 'sentence_break', 'word_break')

	def test_truncates_at_table_boundary(self):
		"""Should not cut mid-table."""
		content = '# Data\n|A|B|C|\n|1|2|3|\n|4|5|6|\n\nAfter table content that continues for a while and makes this long.'
		result, info = smart_truncate(content, max_chars=60)

		# Should truncate after table row ends
		assert info['truncated'] is True
		# Result should either be at a table row end or before the table
		assert result.count('|') % 4 == 0 or '|' not in result  # Complete rows only

	def test_returns_next_start_char(self):
		"""Should return next_start_char for pagination."""
		content = 'A' * 100
		result, info = smart_truncate(content, max_chars=50)

		assert info['truncated'] is True
		assert 'next_start_char' in info
		assert info['next_start_char'] > 0

	def test_handles_start_from_offset(self):
		"""Should handle start_from parameter correctly."""
		content = 'AAABBBCCC'
		result, info = smart_truncate(content, max_chars=100, start_from=3)

		assert result == 'BBBCCC'
		assert info['started_from'] == 3

	def test_error_on_invalid_start_from(self):
		"""Should return error if start_from exceeds content length."""
		content = 'Short'
		result, info = smart_truncate(content, max_chars=100, start_from=100)

		assert 'error' in info


class TestSemanticDataAttr:
	"""Tests for is_semantic_data_attr function."""

	def test_keeps_test_ids(self):
		"""Test identifiers should be kept."""
		assert is_semantic_data_attr('data-testid') is True
		assert is_semantic_data_attr('data-test') is True
		assert is_semantic_data_attr('data-cy') is True
		assert is_semantic_data_attr('data-selenium') is True

	def test_keeps_field_semantics(self):
		"""Field semantic attributes should be kept."""
		assert is_semantic_data_attr('data-field-type') is True
		assert is_semantic_data_attr('data-validation') is True
		assert is_semantic_data_attr('data-format') is True

	def test_keeps_identifiers(self):
		"""Identifier attributes should be kept."""
		assert is_semantic_data_attr('data-id') is True
		assert is_semantic_data_attr('data-product-id') is True
		assert is_semantic_data_attr('data-user-id') is True

	def test_non_data_attrs_pass_through(self):
		"""Non-data-* attributes should always pass."""
		assert is_semantic_data_attr('class') is True
		assert is_semantic_data_attr('id') is True
		assert is_semantic_data_attr('aria-label') is True

	def test_rejects_framework_internals(self):
		"""Framework internal data attributes should be rejected."""
		# These are patterns that don't match our semantic whitelist
		assert is_semantic_data_attr('data-reactid') is False
		assert is_semantic_data_attr('data-v-abc123') is False


class TestSpaStateJsonDetection:
	"""Tests for is_spa_state_json function."""

	def test_detects_react_state(self):
		"""Should detect React framework state."""
		react_state = '{"$$typeof": "Symbol(react.element)", "props": {}}'
		assert is_spa_state_json(react_state) is True

	def test_detects_nextjs_state(self):
		"""Should detect Next.js page data."""
		# Must be >50 chars to pass the minimum length check
		nextjs_state = '{"__NEXT_DATA__": {"props": {"pageProps": {"data": "test content here"}}, "page": "/"}}'
		assert is_spa_state_json(nextjs_state) is True

	def test_detects_nuxt_state(self):
		"""Should detect Nuxt.js state."""
		# Must be >50 chars to pass the minimum length check
		nuxt_state = '{"__NUXT__": {"data": [], "serverRendered": true, "state": {"key": "value"}}}'
		assert is_spa_state_json(nuxt_state) is True

	def test_detects_graphql_typename(self):
		"""Should detect GraphQL __typename patterns."""
		# Must be >50 chars to pass the minimum length check
		graphql_state = '{"__typename": "Query", "data": {"user": {"id": 1, "name": "Test User"}}}'
		assert is_spa_state_json(graphql_state) is True

	def test_preserves_normal_json(self):
		"""Should not flag normal JSON data as SPA state."""
		product_data = '{"name": "Product", "price": 99.99, "inStock": true}'
		assert is_spa_state_json(product_data) is False

	def test_preserves_short_json(self):
		"""Short JSON should not be flagged."""
		short_json = '{"a": 1}'
		assert is_spa_state_json(short_json) is False

	def test_preserves_array_data(self):
		"""Array data should not be flagged unless it has framework markers."""
		array_data = '[{"id": 1, "name": "Item 1"}, {"id": 2, "name": "Item 2"}]'
		assert is_spa_state_json(array_data) is False
