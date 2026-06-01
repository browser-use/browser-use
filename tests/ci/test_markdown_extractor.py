"""Tests for markdown extractor preprocessing."""

from browser_use.dom.markdown_extractor import _preprocess_markdown_content


class TestPreprocessMarkdownContent:
	"""Tests for _preprocess_markdown_content function."""

	def test_preserves_short_lines(self):
		"""Short lines (1-2 chars) should be preserved, not removed."""
		content = '# Items\na\nb\nc\nOK\nNo'
		filtered, _ = _preprocess_markdown_content(content)

		assert 'a' in filtered.split('\n')
		assert 'b' in filtered.split('\n')
		assert 'c' in filtered.split('\n')
		assert 'OK' in filtered.split('\n')
		assert 'No' in filtered.split('\n')

	def test_preserves_single_digit_numbers(self):
		"""Single digit page numbers should be preserved."""
		content = 'Page navigation:\n1\n2\n3\n10'
		filtered, _ = _preprocess_markdown_content(content)

		lines = filtered.split('\n')
		assert '1' in lines
		assert '2' in lines
		assert '3' in lines
		assert '10' in lines

	def test_preserves_markdown_list_items(self):
		"""Markdown list items with short content should be preserved."""
		content = 'Shopping list:\n- a\n- b\n- OK\n- No'
		filtered, _ = _preprocess_markdown_content(content)

		assert '- a' in filtered
		assert '- b' in filtered
		assert '- OK' in filtered
		assert '- No' in filtered

	def test_preserves_state_codes(self):
		"""Two-letter state codes should be preserved."""
		content = 'States:\nCA\nNY\nTX'
		filtered, _ = _preprocess_markdown_content(content)

		lines = filtered.split('\n')
		assert 'CA' in lines
		assert 'NY' in lines
		assert 'TX' in lines

	def test_removes_empty_lines(self):
		"""Empty and whitespace-only lines should be removed."""
		content = 'Header\n\n   \n\nContent'
		filtered, _ = _preprocess_markdown_content(content)

		# Should not have empty lines
		for line in filtered.split('\n'):
			assert line.strip(), f'Found empty line in output: {repr(line)}'

	def test_removes_large_json_blobs(self):
		"""Large JSON-like lines (>100 chars) should be removed."""
		# Create a JSON blob > 100 chars
		json_blob = '{"key": "' + 'x' * 100 + '"}'
		content = f'Header\n{json_blob}\nFooter'
		filtered, _ = _preprocess_markdown_content(content)

		assert json_blob not in filtered
		assert 'Header' in filtered
		assert 'Footer' in filtered

	def test_preserves_small_json(self):
		"""Small JSON objects (<100 chars) should be preserved."""
		small_json = '{"key": "value"}'
		content = f'Header\n{small_json}\nFooter'
		filtered, _ = _preprocess_markdown_content(content)

		assert small_json in filtered

	def test_compresses_multiple_newlines(self):
		"""4+ consecutive newlines should be compressed to max_newlines."""
		content = 'Header\n\n\n\n\nFooter'
		filtered, _ = _preprocess_markdown_content(content, max_newlines=2)

		# After filtering empty lines, we should have just Header and Footer
		lines = [line for line in filtered.split('\n') if line.strip()]
		assert lines == ['Header', 'Footer']

	def test_returns_chars_filtered_count(self):
		"""Should return count of characters removed."""
		content = 'Header\n\n\n\n\nFooter'
		_, chars_filtered = _preprocess_markdown_content(content)

		assert chars_filtered > 0

	def test_strips_result(self):
		"""Result should be stripped of leading/trailing whitespace."""
		content = '  \n\nContent\n\n  '
		filtered, _ = _preprocess_markdown_content(content)

		assert not filtered.startswith(' ')
		assert not filtered.startswith('\n')
		assert not filtered.endswith(' ')
		assert not filtered.endswith('\n')
