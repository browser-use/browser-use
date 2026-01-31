"""
Shared markdown extraction utilities for browser content processing.

This module provides a unified interface for extracting clean markdown from browser content,
used by both the tools service and page actor.
"""

import re
from typing import TYPE_CHECKING, Any

from browser_use.dom.serializer.html_serializer import HTMLSerializer
from browser_use.dom.service import DomService

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession
	from browser_use.browser.watchdogs.dom_watchdog import DOMWatchdog
	from browser_use.dom.views import MarkdownChunk


async def extract_clean_markdown(
	browser_session: 'BrowserSession | None' = None,
	dom_service: DomService | None = None,
	target_id: str | None = None,
	extract_links: bool = False,
) -> tuple[str, dict[str, Any]]:
	"""Extract clean markdown from browser content using enhanced DOM tree.

	This unified function can extract markdown using either a browser session (for tools service)
	or a DOM service with target ID (for page actor).

	Args:
	    browser_session: Browser session to extract content from (tools service path)
	    dom_service: DOM service instance (page actor path)
	    target_id: Target ID for the page (required when using dom_service)
	    extract_links: Whether to preserve links in markdown

	Returns:
	    tuple: (clean_markdown_content, content_statistics)

	Raises:
	    ValueError: If neither browser_session nor (dom_service + target_id) are provided
	"""
	# Validate input parameters
	if browser_session is not None:
		if dom_service is not None or target_id is not None:
			raise ValueError('Cannot specify both browser_session and dom_service/target_id')
		# Browser session path (tools service)
		enhanced_dom_tree = await _get_enhanced_dom_tree_from_browser_session(browser_session)
		current_url = await browser_session.get_current_page_url()
		method = 'enhanced_dom_tree'
	elif dom_service is not None and target_id is not None:
		# DOM service path (page actor)
		# Lazy fetch all_frames inside get_dom_tree if needed (for cross-origin iframes)
		enhanced_dom_tree, _ = await dom_service.get_dom_tree(target_id=target_id, all_frames=None)
		current_url = None  # Not available via DOM service
		method = 'dom_service'
	else:
		raise ValueError('Must provide either browser_session or both dom_service and target_id')

	# Use the HTML serializer with the enhanced DOM tree
	html_serializer = HTMLSerializer(extract_links=extract_links)
	page_html = html_serializer.serialize(enhanced_dom_tree)

	original_html_length = len(page_html)

	# Use markdownify for clean markdown conversion
	from markdownify import markdownify as md

	content = md(
		page_html,
		heading_style='ATX',  # Use # style headings
		strip=['script', 'style'],  # Remove these tags
		bullets='-',  # Use - for unordered lists
		code_language='',  # Don't add language to code blocks
		escape_asterisks=False,  # Don't escape asterisks (cleaner output)
		escape_underscores=False,  # Don't escape underscores (cleaner output)
		escape_misc=False,  # Don't escape other characters (cleaner output)
		autolinks=False,  # Don't convert URLs to <> format
		default_title=False,  # Don't add default title attributes
		keep_inline_images_in=[],  # Don't keep inline images in any tags (we already filter base64 in HTML)
	)

	initial_markdown_length = len(content)

	# Minimal cleanup - markdownify already does most of the work
	content = re.sub(r'%[0-9A-Fa-f]{2}', '', content)  # Remove any remaining URL encoding

	# Apply light preprocessing to clean up excessive whitespace
	content, chars_filtered = _preprocess_markdown_content(content)

	final_filtered_length = len(content)

	# Content statistics
	stats = {
		'method': method,
		'original_html_chars': original_html_length,
		'initial_markdown_chars': initial_markdown_length,
		'filtered_chars_removed': chars_filtered,
		'final_filtered_chars': final_filtered_length,
	}

	# Add URL to stats if available
	if current_url:
		stats['url'] = current_url

	return content, stats


async def _get_enhanced_dom_tree_from_browser_session(browser_session: 'BrowserSession'):
	"""Get enhanced DOM tree from browser session via DOMWatchdog."""
	# Get the enhanced DOM tree from DOMWatchdog
	# This captures the current state of the page including dynamic content, shadow roots, etc.
	dom_watchdog: DOMWatchdog | None = browser_session._dom_watchdog
	assert dom_watchdog is not None, 'DOMWatchdog not available'

	# Use cached enhanced DOM tree if available, otherwise build it
	if dom_watchdog.enhanced_dom_tree is not None:
		return dom_watchdog.enhanced_dom_tree

	# Build the enhanced DOM tree if not cached
	await dom_watchdog._build_dom_tree_without_highlights()
	enhanced_dom_tree = dom_watchdog.enhanced_dom_tree
	assert enhanced_dom_tree is not None, 'Enhanced DOM tree not available'

	return enhanced_dom_tree


# Legacy aliases removed - all code now uses the unified extract_clean_markdown function


def chunk_markdown_by_structure(
	content: str,
	max_chunk_size: int = 100_000,
	overlap_lines: int = 3,
) -> list['MarkdownChunk']:
	"""Split markdown content into structural chunks that never break tables, code blocks, or list items.

	Split priority: headers > double newlines (paragraphs) > table row boundaries > list items > sentences.
	Never splits inside: table rows, code blocks (```...```), list continuations.

	Args:
		content: Full markdown content.
		max_chunk_size: Maximum characters per chunk.
		overlap_lines: Number of lines to carry from end of previous chunk as context overlap.

	Returns:
		List of MarkdownChunk objects.
	"""
	from browser_use.dom.views import MarkdownChunk

	if len(content) <= max_chunk_size:
		return [
			MarkdownChunk(
				content=content,
				start_char=0,
				end_char=len(content),
				chunk_index=0,
				total_chunks=1,
			)
		]

	# Parse content into structural blocks
	blocks = _split_into_structural_blocks(content)

	chunks: list[MarkdownChunk] = []
	current_blocks: list[str] = []
	current_size = 0
	current_start = 0
	char_pos = 0
	table_header: str | None = None

	for block in blocks:
		block_size = len(block)

		# If a single block exceeds max_chunk_size, force-split it at sentence boundaries
		if block_size > max_chunk_size:
			# Flush current accumulated blocks first
			if current_blocks:
				chunk_content = '\n\n'.join(current_blocks)
				chunks.append(
					MarkdownChunk(
						content=chunk_content,
						start_char=current_start,
						end_char=current_start + len(chunk_content),
						chunk_index=len(chunks),
						total_chunks=0,  # filled in later
						has_table_header=table_header is not None,
						overlap_prefix='',
					)
				)
				current_blocks = []
				current_size = 0
				current_start = char_pos

			# Force-split the oversized block
			sub_chunks = _force_split_block(block, max_chunk_size)
			for sub in sub_chunks:
				chunks.append(
					MarkdownChunk(
						content=sub,
						start_char=char_pos,
						end_char=char_pos + len(sub),
						chunk_index=len(chunks),
						total_chunks=0,
						has_table_header=False,
						overlap_prefix='',
					)
				)
				char_pos += len(sub)
			continue

		# Would this block push us over the limit?
		separator_size = 2 if current_blocks else 0  # '\n\n' between blocks
		if current_size + separator_size + block_size > max_chunk_size and current_blocks:
			# Flush current chunk
			chunk_content = '\n\n'.join(current_blocks)
			# Build overlap from last N lines
			overlap = ''
			if overlap_lines > 0:
				last_lines = chunk_content.split('\n')
				overlap = '\n'.join(last_lines[-overlap_lines:])

			chunks.append(
				MarkdownChunk(
					content=chunk_content,
					start_char=current_start,
					end_char=current_start + len(chunk_content),
					chunk_index=len(chunks),
					total_chunks=0,
					has_table_header=table_header is not None,
					overlap_prefix='',
				)
			)

			# Start new chunk with overlap prefix
			current_blocks = []
			current_size = 0
			current_start = char_pos

			# Detect if the block is a table row — carry table header
			if _is_table_row(block) and table_header:
				current_blocks.append(table_header)
				current_size += len(table_header) + 2

		# Track table headers (first row + separator row pattern)
		if _is_table_header(block):
			table_header = block
		elif not _is_table_row(block):
			table_header = None

		current_blocks.append(block)
		current_size += block_size + (2 if len(current_blocks) > 1 else 0)
		char_pos += block_size + 2  # account for \n\n between blocks

	# Flush remaining
	if current_blocks:
		chunk_content = '\n\n'.join(current_blocks)
		chunks.append(
			MarkdownChunk(
				content=chunk_content,
				start_char=current_start,
				end_char=current_start + len(chunk_content),
				chunk_index=len(chunks),
				total_chunks=0,
				has_table_header=table_header is not None,
				overlap_prefix='',
			)
		)

	# Fill in total_chunks
	total = len(chunks)
	for chunk in chunks:
		chunk.total_chunks = total

	return chunks


def _split_into_structural_blocks(content: str) -> list[str]:
	"""Split markdown into structural blocks, keeping tables and code blocks intact.

	A "block" is one of:
	- A header line (# ...)
	- A paragraph (text separated by double newlines)
	- A complete table (all rows from | header to last | row)
	- A complete fenced code block (```...```)
	- A list block (contiguous list items)
	"""
	blocks: list[str] = []
	lines = content.split('\n')
	i = 0
	current_block_lines: list[str] = []

	while i < len(lines):
		line = lines[i]
		stripped = line.strip()

		# Fenced code block — consume until closing fence
		if stripped.startswith('```'):
			# Flush accumulated lines
			if current_block_lines:
				blocks.append('\n'.join(current_block_lines))
				current_block_lines = []

			code_lines = [line]
			i += 1
			while i < len(lines):
				code_lines.append(lines[i])
				if lines[i].strip().startswith('```') and len(code_lines) > 1:
					i += 1
					break
				i += 1
			blocks.append('\n'.join(code_lines))
			continue

		# Table block — consume contiguous rows starting with |
		if stripped.startswith('|'):
			if current_block_lines:
				blocks.append('\n'.join(current_block_lines))
				current_block_lines = []

			table_lines = [line]
			i += 1
			while i < len(lines) and lines[i].strip().startswith('|'):
				table_lines.append(lines[i])
				i += 1
			blocks.append('\n'.join(table_lines))
			continue

		# Header line — its own block
		if stripped.startswith('#'):
			if current_block_lines:
				blocks.append('\n'.join(current_block_lines))
				current_block_lines = []
			blocks.append(line)
			i += 1
			continue

		# Empty line — flush current paragraph block
		if not stripped:
			if current_block_lines:
				blocks.append('\n'.join(current_block_lines))
				current_block_lines = []
			i += 1
			continue

		# Regular content line — accumulate
		current_block_lines.append(line)
		i += 1

	# Flush remaining
	if current_block_lines:
		blocks.append('\n'.join(current_block_lines))

	return [b for b in blocks if b.strip()]


def _is_table_row(block: str) -> bool:
	"""Check if a block is a markdown table (rows starting with |)."""
	return block.strip().startswith('|')


def _is_table_header(block: str) -> bool:
	"""Check if a block looks like a table header (first row + separator row)."""
	lines = block.strip().split('\n')
	if len(lines) >= 2:
		return lines[0].strip().startswith('|') and '---' in lines[1]
	return False


def _force_split_block(block: str, max_size: int) -> list[str]:
	"""Force-split an oversized block at sentence/line boundaries."""
	if len(block) <= max_size:
		return [block]

	chunks: list[str] = []
	lines = block.split('\n')
	current: list[str] = []
	current_size = 0

	for line in lines:
		line_size = len(line) + 1  # +1 for newline
		if current_size + line_size > max_size and current:
			chunks.append('\n'.join(current))
			current = []
			current_size = 0
		current.append(line)
		current_size += line_size

	if current:
		chunks.append('\n'.join(current))

	return chunks


def _preprocess_markdown_content(content: str, max_newlines: int = 3) -> tuple[str, int]:
	"""
	Light preprocessing of markdown output - minimal cleanup with JSON blob removal.

	Args:
	    content: Markdown content to lightly filter
	    max_newlines: Maximum consecutive newlines to allow

	Returns:
	    tuple: (filtered_content, chars_filtered)
	"""
	original_length = len(content)

	# Remove JSON blobs (common in SPAs like LinkedIn, Facebook, etc.)
	# These are often embedded as `{"key":"value",...}` and can be massive
	# Match JSON objects/arrays that are at least 100 chars long
	# This catches SPA state/config data without removing small inline JSON
	content = re.sub(r'`\{["\w].*?\}`', '', content, flags=re.DOTALL)  # Remove JSON in code blocks
	content = re.sub(r'\{"\$type":[^}]{100,}\}', '', content)  # Remove JSON with $type fields (common pattern)
	content = re.sub(r'\{"[^"]{5,}":\{[^}]{100,}\}', '', content)  # Remove nested JSON objects

	# Compress consecutive newlines (4+ newlines become max_newlines)
	content = re.sub(r'\n{4,}', '\n' * max_newlines, content)

	# Remove lines that are only whitespace
	lines = content.split('\n')
	filtered_lines = []
	for line in lines:
		stripped = line.strip()
		# Keep all non-empty lines
		if stripped:
			# Skip lines that look like JSON (start with { or [ and are very long)
			if (stripped.startswith('{') or stripped.startswith('[')) and len(stripped) > 100:
				continue
			filtered_lines.append(line)

	content = '\n'.join(filtered_lines)
	content = content.strip()

	chars_filtered = original_length - len(content)
	return content, chars_filtered
