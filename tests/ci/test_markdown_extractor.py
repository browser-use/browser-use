"""Tests for markdown extractor preprocessing."""

import pytest

from browser_use.dom.markdown_extractor import _preprocess_markdown_content, convert_html_to_markdown


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


class TestPreservesLinksAndEncoding:
	"""Regression tests: markdown links and percent-encoded URLs must survive filtering."""

	def test_preserves_long_markdown_link_lines(self):
		"""A long markdown link line (>100 chars) must not be dropped by the JSON heuristic."""
		link = '[Read the full quarterly earnings report for fiscal year 2025](https://example.com/investor-relations/reports/q4-2025-earnings-full.pdf)'
		assert len(link) > 100
		content = f'Header\n{link}\nFooter'
		filtered, _ = _preprocess_markdown_content(content)

		assert link in filtered

	def test_preserves_long_image_link_lines(self):
		"""A long clickable-image line (starts with [![) must not be dropped."""
		line = '[![Product photo of the deluxe widget](https://cdn.example.com/images/products/deluxe-widget-hero.jpg)](https://example.com/products/deluxe-widget)'
		assert len(line) > 100
		content = f'Intro\n{line}\nOutro'
		filtered, _ = _preprocess_markdown_content(content)

		assert line in filtered

	def test_removes_long_json_array_lines(self):
		"""A valid JSON array blob >100 chars should still be dropped."""
		json_array = '[' + ', '.join(f'{{"id": {i}, "name": "item-{i}"}}' for i in range(10)) + ']'
		assert len(json_array) > 100
		content = f'Header\n{json_array}\nFooter'
		filtered, _ = _preprocess_markdown_content(content)

		assert json_array not in filtered
		assert 'Header' in filtered

	def test_preserves_percent_encoded_urls(self):
		"""Percent-encodings in URLs must survive HTML -> markdown conversion."""
		from browser_use.dom.markdown_extractor import convert_html_to_markdown

		html = '<p>See <a href="https://example.com/my%20file%2Fv2?q=a%26b">the doc</a> here</p>'
		content, _, _ = convert_html_to_markdown(html)

		assert '%20' in content
		assert '%2F' in content
		assert '%26' in content


class TestWhitespaceOnlyInlineElements:
	"""An inline element holding only whitespace must not glue the words around it together."""

	@staticmethod
	def _markdown(html: str) -> str:
		content, _, _ = convert_html_to_markdown(html)
		return content.strip()

	@pytest.mark.parametrize('tag', ['b', 'strong', 'em', 'i', 'u', 's', 'del', 'strike', 'code', 'kbd', 'samp', 'sub', 'sup'])
	def test_word_boundary_survives(self, tag: str):
		"""A page that styles the space between two words still reads as two words."""
		assert self._markdown(f'<p>Hello<{tag}> </{tag}>world</p>') == 'Hello world'

	@pytest.mark.parametrize(
		'html',
		[
			'<p>Hello <b> </b>world</p>',
			'<p>Hello<b> </b> world</p>',
			'<p>Hello <b> </b> world</p>',
			'<p>Hello<b>\n</b>world</p>',
		],
	)
	def test_whitespace_around_the_element_matches_an_unconverted_one(self, html: str):
		"""A styled space now behaves exactly like an unstyled one.

		markdownify does not collapse whitespace across element boundaries, so
		`Hello <span> </span>world` has always produced two spaces. The point of the fix is
		that the boundary exists at all; normalising it here would make `<b>` behave
		differently from `<span>`, which is markdownify's own baseline for an inline element
		it does not convert.
		"""
		assert self._markdown(html) == self._markdown(html.replace('b>', 'span>'))

	def test_word_boundary_survives_an_anchor(self):
		assert self._markdown('<p>Hello<a href="https://x.test"> </a>world</p>') == 'Hello world'

	def test_space_between_two_styled_runs_survives(self):
		"""An editor that emits one element per styled run puts the space in its own element."""
		assert self._markdown('<p><b>First</b><b> </b><b>Last</b></p>') == '**First** **Last**'

	def test_non_breaking_space_is_kept_as_itself(self):
		assert self._markdown('<p>Hello<b>&#160;</b>world</p>') == 'Hello world'

	@pytest.mark.parametrize(
		('html', 'expected'),
		[
			('<p>Hello <b>bold</b> world</p>', 'Hello **bold** world'),
			('<p>Hello <em>it</em> world</p>', 'Hello *it* world'),
			('<p>Hello <code>x</code> world</p>', 'Hello `x` world'),
			('<p>Hello <a href="https://x.test">site</a> world</p>', 'Hello [site](https://x.test) world'),
			('<p>Hello<b></b>world</p>', 'Helloworld'),
		],
	)
	def test_elements_with_content_are_unchanged(self, html: str, expected: str):
		"""The control: only an element with nothing but whitespace in it is passed through."""
		assert self._markdown(html) == expected
