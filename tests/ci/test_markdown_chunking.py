"""Tests for structure-aware markdown chunking."""

from markdownify import markdownify as md
from pytest_httpserver import HTTPServer

from browser_use.dom.markdown_extractor import chunk_markdown_by_structure

# ---------------------------------------------------------------------------
# Unit tests — synchronous, no browser needed
# ---------------------------------------------------------------------------


class TestChunkMarkdownBasic:
	"""Basic chunking behaviour."""

	def test_short_content_single_chunk(self):
		content = '# Hello\n\nSome short content.'
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=100_000)
		assert len(chunks) == 1
		assert chunks[0].content == content
		assert chunks[0].chunk_index == 0
		assert chunks[0].total_chunks == 1
		assert chunks[0].has_more is False

	def test_empty_content(self):
		chunks = chunk_markdown_by_structure('', max_chunk_chars=100)
		assert len(chunks) == 1
		assert chunks[0].content == ''
		assert chunks[0].has_more is False

	def test_chunk_offsets_cover_full_content(self):
		"""Chunk offsets should cover the entire original content without gaps."""
		content = '# Header\n\nParagraph one.\n\n# Header 2\n\nParagraph two.'
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=20)
		# Verify no gaps between consecutive chunks
		for i in range(1, len(chunks)):
			assert chunks[i].char_offset_start == chunks[i - 1].char_offset_end, (
				f'Gap between chunk {i - 1} end ({chunks[i - 1].char_offset_end}) '
				f'and chunk {i} start ({chunks[i].char_offset_start})'
			)
		# First chunk starts at 0
		assert chunks[0].char_offset_start == 0
		# Last chunk ends at content length
		assert chunks[-1].char_offset_end == len(content)


class TestChunkMarkdownHeaders:
	"""Header boundary splitting."""

	def test_splits_at_header_boundary(self):
		"""Chunks should prefer splitting at header boundaries."""
		section_a = '# Section A\n\n' + 'x' * 50
		section_b = '\n\n# Section B\n\n' + 'y' * 50
		content = section_a + section_b
		# Set limit so section_a fits but section_a + section_b doesn't
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=len(section_a) + 5)
		assert len(chunks) >= 2
		# First chunk should contain Section A header
		assert '# Section A' in chunks[0].content
		# Second chunk should start with or contain Section B header
		assert '# Section B' in chunks[1].content


class TestChunkMarkdownHeaderPreferred:
	"""Header-preferred splitting ensures chunks start at semantic boundaries."""

	def test_header_preferred_split_moves_header_to_next_chunk(self):
		"""When a header sits in the middle of an overflowing chunk, split before it."""
		# Build content: para_a (big) + header_b + para_b (small)
		para_a = 'A' * 600
		header_b = '# Section B'
		para_b = 'B' * 100
		content = f'{para_a}\n\n{header_b}\n\n{para_b}'
		# Limit forces a split; header is near end of first chunk
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=700)
		assert len(chunks) >= 2
		# The header should be the START of the second chunk, not the end of the first
		assert chunks[1].content.lstrip().startswith('# Section B')
		# First chunk should NOT contain the header
		assert '# Section B' not in chunks[0].content

	def test_header_preferred_split_doesnt_create_tiny_chunks(self):
		"""Don't split at a header that would make the prefix chunk < 50% of limit."""
		header_a = '# Section A'
		para_a = 'A' * 30  # very small before header
		header_b = '# Section B'
		para_b = 'B' * 600
		content = f'{header_a}\n\n{para_a}\n\n{header_b}\n\n{para_b}'
		# With a limit of 700, header_b is near the start — splitting there would
		# leave a tiny prefix chunk. The algo should NOT split there.
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=700)
		# First chunk should contain both headers (no tiny split)
		assert '# Section A' in chunks[0].content
		assert '# Section B' in chunks[0].content


class TestChunkMarkdownCodeFence:
	"""Code fence blocks never split."""

	def test_code_fence_not_split(self):
		code_block = '```python\n' + 'x = 1\n' * 100 + '```'
		content = '# Title\n\n' + code_block + '\n\n# Footer\n\nDone.'
		# Limit smaller than the code block — it should still stay in one chunk (soft limit)
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=50)
		# Find the chunk containing the code block
		code_chunks = [c for c in chunks if '```python' in c.content and '```' in c.content.split('```python')[1]]
		assert len(code_chunks) >= 1, 'Code fence should appear intact in at least one chunk'

	def test_unclosed_code_fence(self):
		"""Unclosed code fence should still be kept as one block."""
		content = '# Title\n\n```python\nx = 1\ny = 2'
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=100_000)
		assert len(chunks) == 1
		assert '```python' in chunks[0].content
		assert 'y = 2' in chunks[0].content


class TestChunkMarkdownTable:
	"""Table rows never split mid-row."""

	def test_table_not_split_mid_row(self):
		header = '| Name | Value |'
		separator = '| --- | --- |'
		rows = [f'| item{i} | val{i} |' for i in range(50)]
		table = '\n'.join([header, separator] + rows)
		content = '# Data\n\n' + table

		# Use a limit that would fall in the middle of the table
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=200)

		for chunk in chunks:
			lines = chunk.content.split('\n')
			for line in lines:
				stripped = line.strip()
				if stripped.startswith('|') and stripped.endswith('|'):
					# Each table row line should be complete (start and end with |)
					assert stripped.count('|') >= 3, f'Incomplete table row: {stripped}'

	def test_table_header_in_overlap_for_continuation(self):
		"""When a table spans multiple chunks, the header should be in the overlap prefix."""
		header = '| Col1 | Col2 |'
		separator = '| --- | --- |'
		rows = [f'| r{i} | d{i} |' for i in range(100)]
		table = '\n'.join([header, separator] + rows)
		content = table

		# Force split within the table
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=300)

		if len(chunks) > 1:
			# Second chunk should have table header in overlap
			assert '| Col1 | Col2 |' in chunks[1].overlap_prefix
			assert '| --- | --- |' in chunks[1].overlap_prefix

	def test_table_header_carried_across_three_plus_chunks(self):
		"""Table header must persist in overlap for ALL continuation chunks, not just the second."""
		header = '| Col1 | Col2 |'
		separator = '| --- | --- |'
		rows = [f'| row{i} | data{i} |' for i in range(200)]
		table = '\n'.join([header, separator] + rows)
		content = table

		# Force many small chunks
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=200)
		assert len(chunks) >= 3, f'Expected >=3 chunks, got {len(chunks)}'

		# Every chunk after the first should carry the table header in its overlap
		for i in range(1, len(chunks)):
			assert '| Col1 | Col2 |' in chunks[i].overlap_prefix, f'Chunk {i} missing table header in overlap'
			assert '| --- | --- |' in chunks[i].overlap_prefix, f'Chunk {i} missing table separator in overlap'


class TestChunkMarkdownListItems:
	"""List item continuations stay together."""

	def test_list_items_not_split(self):
		items = '\n'.join([f'- Item {i} with some description text' for i in range(50)])
		content = '# List\n\n' + items

		chunks = chunk_markdown_by_structure(content, max_chunk_chars=200)
		for chunk in chunks:
			lines = chunk.content.split('\n')
			for line in lines:
				stripped = line.strip()
				if stripped.startswith('- '):
					# Each list item should be a complete item
					assert 'Item' in stripped


class TestChunkMarkdownStartFromChar:
	"""start_from_char parameter returns correct chunk."""

	def test_start_from_char_returns_correct_chunk(self):
		section_a = '# A\n\nContent A here.'
		section_b = '\n\n# B\n\nContent B here.'
		content = section_a + section_b
		# Chunk at header boundaries
		all_chunks = chunk_markdown_by_structure(content, max_chunk_chars=len(section_a) + 5)

		if len(all_chunks) > 1:
			# Request from char offset within second chunk
			mid = all_chunks[1].char_offset_start + 1
			filtered = chunk_markdown_by_structure(content, max_chunk_chars=len(section_a) + 5, start_from_char=mid)
			assert len(filtered) >= 1
			assert filtered[0].chunk_index == all_chunks[1].chunk_index

	def test_start_from_char_past_end_returns_empty(self):
		content = '# Hello\n\nWorld.'
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=100_000, start_from_char=99999)
		assert chunks == []

	def test_start_from_char_zero_returns_all(self):
		content = '# Hello\n\nWorld.'
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=100_000, start_from_char=0)
		assert len(chunks) == 1


class TestChunkMarkdownOverlap:
	"""Overlap lines carry context."""

	def test_overlap_lines_carry_context(self):
		lines_content = '\n'.join([f'Line {i}' for i in range(100)])
		content = lines_content

		chunks = chunk_markdown_by_structure(content, max_chunk_chars=200, overlap_lines=3)
		if len(chunks) > 1:
			# Second chunk should have overlap from first chunk
			assert chunks[1].overlap_prefix != ''
			# Overlap should contain lines from the end of the previous chunk
			overlap_lines = chunks[1].overlap_prefix.split('\n')
			assert len(overlap_lines) <= 3 + 2  # some flexibility for table headers etc.

	def test_no_overlap_on_first_chunk(self):
		content = '# A\n\nSome content.\n\n# B\n\nMore content.'
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=25)
		assert chunks[0].overlap_prefix == ''


class TestChunkMarkdownMixed:
	"""Mixed content scenarios."""

	def test_paragraph_splitting(self):
		"""Paragraphs separated by blank lines are separate blocks."""
		p1 = 'First paragraph with text.'
		p2 = 'Second paragraph with more text.'
		content = f'{p1}\n\n{p2}'
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=30)
		# Should produce multiple chunks
		assert len(chunks) >= 2

	def test_single_oversized_block_allowed(self):
		"""A single block bigger than max_chunk_chars is allowed (soft limit)."""
		big_para = 'x' * 200
		content = big_para
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=50)
		assert len(chunks) == 1
		assert chunks[0].content == big_para


# ---------------------------------------------------------------------------
# HTML → markdown → chunk pipeline tests
# ---------------------------------------------------------------------------


class TestHTMLToMarkdownChunking:
	"""End-to-end: HTML table → markdown → chunks."""

	def test_large_table_produces_valid_chunks(self):
		"""200-row HTML table → markdown → chunks should produce valid table rows in every chunk."""
		rows = ''.join(f'<tr><td>Row {i}</td><td>Val {i}</td></tr>' for i in range(200))
		html = f'<table><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table>'
		markdown = md(html, heading_style='ATX')

		chunks = chunk_markdown_by_structure(markdown, max_chunk_chars=500)
		assert len(chunks) > 1, 'Should produce multiple chunks for 200 rows'

		for chunk in chunks:
			lines = chunk.content.strip().split('\n')
			for line in lines:
				s = line.strip()
				if s.startswith('|') and s.endswith('|'):
					# Every table line should have consistent column count
					assert s.count('|') >= 3

	def test_table_without_thead_normalization(self):
		"""Table with <th> in first <tr> but no <thead> should still produce proper markdown."""
		html = '<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>'
		markdown = md(html, heading_style='ATX')
		# Verify markdownify produced a proper table (with separator row)
		assert '---' in markdown or '| A |' in markdown


# ---------------------------------------------------------------------------
# Integration tests — require browser + httpserver
# ---------------------------------------------------------------------------


class TestTableNormalizationIntegration:
	"""Integration tests using browser session and httpserver."""

	async def test_table_without_thead_normalized_via_serializer(self, browser_session, httpserver: HTTPServer):
		"""Tables without <thead> should get normalized by HTMLSerializer during extraction."""
		html = """
		<html><body>
		<table>
			<tr><th>Header1</th><th>Header2</th></tr>
			<tr><td>data1</td><td>data2</td></tr>
			<tr><td>data3</td><td>data4</td></tr>
		</table>
		</body></html>
		"""
		httpserver.expect_request('/table-test').respond_with_data(html, content_type='text/html')
		url = httpserver.url_for('/table-test')

		await browser_session.navigate_to(url)

		from browser_use.dom.markdown_extractor import extract_clean_markdown

		content, _ = await extract_clean_markdown(browser_session=browser_session)

		# Should have proper markdown table with separator
		assert '|' in content
		# The header should be present
		assert 'Header1' in content
		assert 'Header2' in content

	async def test_large_table_extraction_preserves_structure(self, browser_session, httpserver: HTTPServer):
		"""Large table extraction should produce structure-aware chunks."""
		rows = ''.join(f'<tr><td>Name{i}</td><td>Value{i}</td></tr>' for i in range(300))
		html = f"""
		<html><body>
		<table>
			<tr><th>Name</th><th>Value</th></tr>
			{rows}
		</table>
		</body></html>
		"""
		httpserver.expect_request('/big-table').respond_with_data(html, content_type='text/html')
		url = httpserver.url_for('/big-table')

		await browser_session.navigate_to(url)

		from browser_use.dom.markdown_extractor import extract_clean_markdown

		content, _ = await extract_clean_markdown(browser_session=browser_session)

		# Chunk with a small limit to force multiple chunks
		chunks = chunk_markdown_by_structure(content, max_chunk_chars=2000)

		# Should produce multiple chunks
		assert len(chunks) > 1

		# Each chunk should have complete table rows
		for chunk in chunks:
			for line in chunk.content.split('\n'):
				s = line.strip()
				if s.startswith('|') and s.endswith('|'):
					assert s.count('|') >= 3, f'Incomplete table row: {s}'
