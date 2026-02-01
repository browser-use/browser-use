"""Tests for PR 3: Structure-aware content chunking in markdown_extractor."""

from browser_use.dom.markdown_extractor import (
	_force_split_block,
	_is_list_item,
	_is_table_header,
	_is_table_row,
	_split_into_structural_blocks,
	chunk_markdown_by_structure,
)

# ── Helper function tests ────────────────────────────────────────────────────


class TestStructuralBlockSplitting:
	def test_paragraphs(self):
		content = 'Paragraph one.\n\nParagraph two.\n\nParagraph three.'
		blocks = _split_into_structural_blocks(content)
		assert len(blocks) == 3
		assert blocks[0] == 'Paragraph one.'
		assert blocks[1] == 'Paragraph two.'
		assert blocks[2] == 'Paragraph three.'

	def test_headers_as_separate_blocks(self):
		content = '# Header 1\n\nSome text.\n\n## Header 2\n\nMore text.'
		blocks = _split_into_structural_blocks(content)
		assert blocks[0] == '# Header 1'
		assert blocks[1] == 'Some text.'
		assert blocks[2] == '## Header 2'
		assert blocks[3] == 'More text.'

	def test_table_kept_intact(self):
		content = 'Before table.\n\n| Name | Price |\n| --- | --- |\n| Widget | $9.99 |\n| Gadget | $19.99 |\n\nAfter table.'
		blocks = _split_into_structural_blocks(content)
		# Should be: "Before table.", table block, "After table."
		assert len(blocks) == 3
		table_block = blocks[1]
		assert table_block.startswith('| Name')
		assert '| Gadget | $19.99 |' in table_block
		# Table should have 4 lines (header, separator, 2 data rows)
		assert len(table_block.split('\n')) == 4

	def test_code_block_kept_intact(self):
		content = 'Before code.\n\n```python\ndef foo():\n    return 42\n```\n\nAfter code.'
		blocks = _split_into_structural_blocks(content)
		assert len(blocks) == 3
		code_block = blocks[1]
		assert code_block.startswith('```python')
		assert 'return 42' in code_block
		assert code_block.endswith('```')

	def test_empty_lines_between_content(self):
		content = 'Line one.\n\n\n\nLine two.'
		blocks = _split_into_structural_blocks(content)
		assert len(blocks) == 2

	def test_mixed_content(self):
		content = (
			'# Title\n\nSome intro text.\n\n| Col1 | Col2 |\n| --- | --- |\n| A | B |\n\n```\ncode here\n```\n\nFinal paragraph.'
		)
		blocks = _split_into_structural_blocks(content)
		assert blocks[0] == '# Title'
		assert blocks[1] == 'Some intro text.'
		assert blocks[2].startswith('| Col1')
		assert blocks[3].startswith('```')
		assert blocks[4] == 'Final paragraph.'


class TestTableDetection:
	def test_is_table_row(self):
		assert _is_table_row('| Name | Price |')
		assert _is_table_row('| --- | --- |')
		assert not _is_table_row('Not a table row')
		assert not _is_table_row('# Header')

	def test_is_table_header(self):
		assert _is_table_header('| Name | Price |\n| --- | --- |')
		assert _is_table_header('| A | B | C |\n| --- | --- | --- |\n| 1 | 2 | 3 |')
		assert not _is_table_header('| Name | Price |')  # No separator
		assert not _is_table_header('Just text')


class TestListDetection:
	def test_unordered_list_items(self):
		assert _is_list_item('- item')
		assert _is_list_item('* item')
		assert _is_list_item('+ item')

	def test_ordered_list_items(self):
		assert _is_list_item('1. item')
		assert _is_list_item('10. item')
		assert _is_list_item('1) item')

	def test_non_list_items(self):
		assert not _is_list_item('Regular text')
		assert not _is_list_item('# Header')
		assert not _is_list_item('| table |')

	def test_list_block_kept_intact(self):
		content = 'Before list.\n\n- item 1\n- item 2\n- item 3\n\nAfter list.'
		blocks = _split_into_structural_blocks(content)
		assert len(blocks) == 3
		assert blocks[0] == 'Before list.'
		assert blocks[1] == '- item 1\n- item 2\n- item 3'
		assert blocks[2] == 'After list.'

	def test_ordered_list_block_kept_intact(self):
		content = 'Intro.\n\n1. First\n2. Second\n3. Third\n\nEnd.'
		blocks = _split_into_structural_blocks(content)
		assert len(blocks) == 3
		assert blocks[1] == '1. First\n2. Second\n3. Third'

	def test_list_with_indented_continuation(self):
		content = 'Text.\n\n- item 1\n  continuation\n- item 2\n\nMore text.'
		blocks = _split_into_structural_blocks(content)
		assert len(blocks) == 3
		list_block = blocks[1]
		assert '- item 1' in list_block
		assert 'continuation' in list_block
		assert '- item 2' in list_block


class TestForceSplitBlock:
	def test_small_block_unchanged(self):
		block = 'Small text'
		result = _force_split_block(block, max_size=1000)
		assert len(result) == 1
		assert result[0] == block

	def test_large_block_split_at_lines(self):
		lines = [f'Line {i}: ' + 'x' * 50 for i in range(100)]
		block = '\n'.join(lines)
		result = _force_split_block(block, max_size=500)
		assert len(result) > 1
		# Every chunk should be <= max_size (with possible single-line overshoot)
		for chunk in result:
			assert len(chunk) <= 500 or '\n' not in chunk


# ── chunk_markdown_by_structure tests ────────────────────────────────────────


class TestChunkMarkdownByStructure:
	def test_small_content_single_chunk(self):
		content = 'Short content.'
		chunks = chunk_markdown_by_structure(content, max_chunk_size=1000)
		assert len(chunks) == 1
		assert chunks[0].content == content
		assert chunks[0].chunk_index == 0
		assert chunks[0].total_chunks == 1

	def test_large_content_multiple_chunks(self):
		# Create content that exceeds max_chunk_size
		paragraphs = [f'Paragraph {i}: ' + 'word ' * 100 for i in range(20)]
		content = '\n\n'.join(paragraphs)
		chunks = chunk_markdown_by_structure(content, max_chunk_size=1000)
		assert len(chunks) > 1
		# All chunks should have correct total_chunks
		for chunk in chunks:
			assert chunk.total_chunks == len(chunks)
		# Chunk indices should be sequential
		for i, chunk in enumerate(chunks):
			assert chunk.chunk_index == i

	def test_table_not_split_mid_row(self):
		# Create a table with many rows
		header = '| Name | Price | SKU |'
		separator = '| --- | --- | --- |'
		rows = [f'| Product {i} | ${i}.99 | SKU{i:03d} |' for i in range(50)]
		table = '\n'.join([header, separator] + rows)
		content = f'# Products\n\n{table}\n\nEnd of list.'

		chunks = chunk_markdown_by_structure(content, max_chunk_size=500)

		# Verify no chunk has a partial table row (every | line should have matching |)
		for chunk in chunks:
			lines = chunk.content.split('\n')
			for line in lines:
				stripped = line.strip()
				if stripped.startswith('|'):
					# Count pipe characters — should be even (start + end + separators)
					pipe_count = stripped.count('|')
					assert pipe_count >= 2, f'Partial table row detected: {stripped}'

	def test_code_block_not_split(self):
		code = '```python\n' + '\n'.join([f'line_{i} = {i}' for i in range(20)]) + '\n```'
		content = f'Before code.\n\n{code}\n\nAfter code.'

		# Use a chunk size that can fit the code block
		chunks = chunk_markdown_by_structure(content, max_chunk_size=max(len(code) + 100, 600))

		# Find the chunk containing the code block
		code_chunk = None
		for chunk in chunks:
			if '```python' in chunk.content:
				code_chunk = chunk
				break
		assert code_chunk is not None
		assert '```python' in code_chunk.content
		assert code_chunk.content.rstrip().endswith('```') or 'After code.' in code_chunk.content

	def test_header_boundaries_respected(self):
		content = '# Section 1\n\nContent for section 1.\n\n# Section 2\n\nContent for section 2.'
		chunks = chunk_markdown_by_structure(content, max_chunk_size=50)
		# Every header line should appear at the start of a chunk (index 0)
		for chunk in chunks:
			lines = chunk.content.split('\n')
			for i, line in enumerate(lines):
				if line.startswith('#') and i > 0:
					# Header mid-chunk is only acceptable if preceded by empty line
					assert lines[i - 1].strip() == '', (
						f'Header "{line}" at line {i} in chunk {chunk.chunk_index} '
						f'is not at chunk start and not preceded by empty line'
					)

	def test_end_to_end_large_table(self):
		"""200-row HTML table → chunk → verify all rows present across chunks."""
		header = '| Col1 | Col2 | Col3 |'
		separator = '| --- | --- | --- |'
		rows = [f'| Row{i} | Data{i} | Value{i} |' for i in range(200)]
		table = '\n'.join([header, separator] + rows)

		chunks = chunk_markdown_by_structure(table, max_chunk_size=2000)

		# Collect all row identifiers from all chunks
		found_rows = set()
		for chunk in chunks:
			for line in chunk.content.split('\n'):
				stripped = line.strip()
				if stripped.startswith('| Row'):
					# Extract row number
					parts = stripped.split('|')
					if len(parts) >= 2:
						row_id = parts[1].strip()
						found_rows.add(row_id)

		# All 200 rows should be present
		for i in range(200):
			assert f'Row{i}' in found_rows, f'Row{i} missing from chunks'

	def test_overlap_prefix_populated(self):
		"""overlap_prefix should carry context from the previous chunk's last N lines."""
		paragraphs = [f'Paragraph {i}: some content here.' for i in range(10)]
		content = '\n\n'.join(paragraphs)
		chunks = chunk_markdown_by_structure(content, max_chunk_size=200, overlap_lines=2)
		assert len(chunks) >= 2
		# First chunk should have empty overlap (no previous chunk)
		assert chunks[0].overlap_prefix == ''
		# Subsequent chunks should have non-empty overlap from previous chunk
		for i in range(1, len(chunks)):
			assert chunks[i].overlap_prefix != '', f'Chunk {i} should have overlap_prefix from previous chunk'

	def test_chunk_metadata(self):
		content = 'A' * 500 + '\n\n' + 'B' * 500 + '\n\n' + 'C' * 500
		chunks = chunk_markdown_by_structure(content, max_chunk_size=600)
		assert len(chunks) >= 2
		# start_char should be non-decreasing
		for i in range(1, len(chunks)):
			assert chunks[i].start_char >= chunks[i - 1].start_char
