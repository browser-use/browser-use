"""
Shared markdown extraction utilities for browser content processing.

This module provides a unified interface for extracting clean markdown from browser content,
used by both the tools service and page actor.

Key improvements over naive HTML-to-markdown:
1. Uses accessibility tree to identify main content vs boilerplate
2. Semantic JSON detection instead of arbitrary size thresholds
3. Structure-aware preprocessing that preserves tables, forms, lists
4. Extraction metadata for transparency about what was filtered
"""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from browser_use.dom.content_filter import (
	find_main_content_root,
	is_spa_state_json,
)
from browser_use.dom.serializer.html_serializer import HTMLSerializer
from browser_use.dom.service import DomService

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession
	from browser_use.browser.watchdogs.dom_watchdog import DOMWatchdog
	from browser_use.tools.views import ExtractionMode


@dataclass
class ExtractionResult:
	"""Result of content extraction with metadata."""

	content: str
	stats: dict[str, Any] = field(default_factory=dict)
	removed_regions: list[str] = field(default_factory=list)
	truncation_info: dict[str, Any] | None = None
	main_content_found: bool = False


async def extract_clean_markdown(
	browser_session: 'BrowserSession | None' = None,
	dom_service: DomService | None = None,
	target_id: str | None = None,
	extract_links: bool = False,
	mode: 'ExtractionMode | None' = None,
) -> tuple[str, dict[str, Any]]:
	"""Extract clean markdown from browser content using enhanced DOM tree.

	This unified function can extract markdown using either a browser session (for tools service)
	or a DOM service with target ID (for page actor).

	Args:
		browser_session: Browser session to extract content from (tools service path)
		dom_service: DOM service instance (page actor path)
		target_id: Target ID for the page (required when using dom_service)
		extract_links: Whether to preserve links in markdown
		mode: Extraction mode (auto, full_page, main_content, interactive, structured)

	Returns:
		tuple: (clean_markdown_content, content_statistics)

	Raises:
		ValueError: If neither browser_session nor (dom_service + target_id) are provided
	"""
	# Import here to avoid circular imports
	from browser_use.tools.views import ExtractionMode

	if mode is None:
		mode = ExtractionMode.AUTO

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
		enhanced_dom_tree, _ = await dom_service.get_dom_tree(target_id=target_id, all_frames=None)
		current_url = None
		method = 'dom_service'
	else:
		raise ValueError('Must provide either browser_session or both dom_service and target_id')

	# Try to find main content region using accessibility tree
	removed_regions: list[str] = []
	main_content_found = False

	if mode in (ExtractionMode.AUTO, ExtractionMode.MAIN_CONTENT):
		main_content_root = find_main_content_root(enhanced_dom_tree)
		if main_content_root is not None:
			main_content_found = True
			# Use main content root for extraction
			extraction_root = main_content_root
			removed_regions.append('Used main content region (skipped navigation, header, footer)')
		else:
			# Fall back to full page
			extraction_root = enhanced_dom_tree
			if mode == ExtractionMode.AUTO:
				removed_regions.append('No main content region found - using full page')
	else:
		extraction_root = enhanced_dom_tree

	# Use the HTML serializer with the enhanced DOM tree
	html_serializer = HTMLSerializer(extract_links=extract_links)
	page_html = html_serializer.serialize(extraction_root)

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
		keep_inline_images_in=[],  # Don't keep inline images
	)

	initial_markdown_length = len(content)

	# Minimal cleanup - markdownify already does most of the work
	content = re.sub(r'%[0-9A-Fa-f]{2}', '', content)  # Remove any remaining URL encoding

	# Apply smart preprocessing to clean up content
	content, preprocess_stats = _preprocess_markdown_content(content, mode)

	final_filtered_length = len(content)

	# Build content statistics
	stats = {
		'method': method,
		'extraction_mode': mode.value if mode else 'auto',
		'original_html_chars': original_html_length,
		'initial_markdown_chars': initial_markdown_length,
		'filtered_chars_removed': preprocess_stats['chars_filtered'],
		'final_filtered_chars': final_filtered_length,
		'main_content_found': main_content_found,
		'removed_regions': removed_regions,
		'preprocessing': preprocess_stats,
	}

	# Add URL to stats if available
	if current_url:
		stats['url'] = current_url

	return content, stats


async def _get_enhanced_dom_tree_from_browser_session(browser_session: 'BrowserSession'):
	"""Get enhanced DOM tree from browser session via DOMWatchdog."""
	dom_watchdog: 'DOMWatchdog | None' = browser_session._dom_watchdog
	assert dom_watchdog is not None, 'DOMWatchdog not available'

	# Use cached enhanced DOM tree if available, otherwise build it
	if dom_watchdog.enhanced_dom_tree is not None:
		return dom_watchdog.enhanced_dom_tree

	# Build the enhanced DOM tree if not cached
	await dom_watchdog._build_dom_tree_without_highlights()
	enhanced_dom_tree = dom_watchdog.enhanced_dom_tree
	assert enhanced_dom_tree is not None, 'Enhanced DOM tree not available'

	return enhanced_dom_tree


def _preprocess_markdown_content(
	content: str,
	mode: 'ExtractionMode | None' = None,
	max_newlines: int = 3,
) -> tuple[str, dict[str, Any]]:
	"""
	Smart preprocessing of markdown output using semantic detection.

	Unlike the old approach that used arbitrary size thresholds (100 chars),
	this uses pattern detection to identify SPA state vs legitimate content.

	Args:
		content: Markdown content to filter
		mode: Extraction mode for context-aware filtering
		max_newlines: Maximum consecutive newlines to allow

	Returns:
		tuple: (filtered_content, preprocessing_stats)
	"""
	from browser_use.tools.views import ExtractionMode

	if mode is None:
		mode = ExtractionMode.AUTO

	original_length = len(content)
	stats: dict[str, Any] = {
		'json_blobs_removed': 0,
		'empty_lines_removed': 0,
		'whitespace_normalized': False,
		'chars_filtered': 0,
	}

	# Step 1: Remove JSON that looks like SPA framework state
	# Use semantic detection instead of size-based heuristics
	content, json_removed = _remove_spa_state_json(content)
	stats['json_blobs_removed'] = json_removed

	# Step 2: Compress consecutive newlines (4+ newlines become max_newlines)
	if '\n\n\n\n' in content:
		content = re.sub(r'\n{4,}', '\n' * max_newlines, content)
		stats['whitespace_normalized'] = True

	# Step 3: Remove lines that are only whitespace (but preserve structure)
	lines = content.split('\n')
	filtered_lines = []
	empty_count = 0

	for line in lines:
		stripped = line.strip()

		# Always keep non-empty lines
		if stripped:
			filtered_lines.append(line)
			continue

		# Keep some empty lines for structure (but not too many consecutive)
		if empty_count < 2:
			filtered_lines.append('')
			empty_count += 1
		else:
			stats['empty_lines_removed'] += 1

		# Reset counter on non-empty
		if stripped:
			empty_count = 0

	content = '\n'.join(filtered_lines)
	content = content.strip()

	stats['chars_filtered'] = original_length - len(content)
	return content, stats


def _remove_spa_state_json(content: str) -> tuple[str, int]:
	"""Remove SPA framework state JSON using semantic detection.

	Instead of blindly removing JSON over a size threshold, this detects
	patterns that indicate framework state (React, Vue, Angular, etc.).

	Args:
		content: Markdown content

	Returns:
		tuple: (filtered_content, count_of_blobs_removed)
	"""
	removed_count = 0

	# Pattern 1: JSON in markdown code blocks that looks like framework state
	def replace_code_json(match: re.Match) -> str:
		nonlocal removed_count
		json_content = match.group(1)
		if is_spa_state_json(json_content):
			removed_count += 1
			return ''
		return match.group(0)

	# Match ```json ... ``` or `{...}` code blocks
	content = re.sub(r'```(?:json)?\s*(\{[^`]+\})\s*```', replace_code_json, content, flags=re.DOTALL)
	content = re.sub(r'`(\{[^`]{50,}\})`', replace_code_json, content)

	# Pattern 2: Standalone JSON lines that look like framework state
	lines = content.split('\n')
	filtered_lines = []

	for line in lines:
		stripped = line.strip()

		# Check if line is JSON-like
		if (stripped.startswith('{') or stripped.startswith('[')) and len(stripped) > 50:
			if is_spa_state_json(stripped):
				removed_count += 1
				continue

		filtered_lines.append(line)

	content = '\n'.join(filtered_lines)

	return content, removed_count


def smart_truncate(
	content: str,
	max_chars: int,
	start_from: int = 0,
) -> tuple[str, dict[str, Any]]:
	"""Truncate content at structure-aware boundaries.

	Unlike naive truncation that might cut mid-table or mid-form,
	this finds safe truncation points that preserve document structure.

	Args:
		content: Content to truncate
		max_chars: Maximum characters allowed
		start_from: Starting offset (for pagination)

	Returns:
		tuple: (truncated_content, truncation_info)
	"""
	# Apply start offset
	if start_from > 0:
		if start_from >= len(content):
			return '', {
				'error': f'start_from_char ({start_from}) exceeds content length ({len(content)})',
				'truncated': False,
			}
		content = content[start_from:]

	# No truncation needed
	if len(content) <= max_chars:
		return content, {
			'truncated': False,
			'original_length': len(content) + start_from,
			'final_length': len(content),
			'started_from': start_from,
		}

	# Find structure boundaries for safe truncation
	truncation_info: dict[str, Any] = {
		'truncated': True,
		'original_length': len(content) + start_from,
		'started_from': start_from,
		'truncation_method': 'unknown',
	}

	# Strategy 1: Find table boundary (don't cut mid-table)
	# Look for table end markers in the truncation window
	search_start = max(0, max_chars - 2000)
	search_end = max_chars

	# Check if we're inside a table
	table_start = content.rfind('|', search_start, search_end)
	if table_start > 0:
		# Find the last complete table row
		last_row_end = content.rfind('|\n', search_start, search_end)
		if last_row_end > 0 and last_row_end > search_start:
			# Check if there's a non-table line after this
			next_line_start = last_row_end + 2
			if next_line_start < len(content):
				next_line = content[next_line_start : next_line_start + 50]
				if not next_line.strip().startswith('|'):
					# Safe to truncate after the table
					truncate_at = last_row_end + 1
					truncation_info['truncation_method'] = 'after_table_row'
					truncation_info['truncate_at'] = truncate_at
					truncation_info['next_start_char'] = start_from + truncate_at
					truncation_info['final_length'] = truncate_at
					return content[:truncate_at], truncation_info

	# Strategy 2: Find heading boundary
	heading_match = None
	for pattern in [r'\n#{1,6} ', r'\n\*\*[^*]+\*\*\n']:
		matches = list(re.finditer(pattern, content[search_start:search_end]))
		if matches:
			# Use the last heading in the search window
			heading_match = matches[-1]
			break

	if heading_match:
		truncate_at = search_start + heading_match.start()
		if truncate_at > search_start:
			truncation_info['truncation_method'] = 'before_heading'
			truncation_info['truncate_at'] = truncate_at
			truncation_info['next_start_char'] = start_from + truncate_at
			truncation_info['final_length'] = truncate_at
			return content[:truncate_at], truncation_info

	# Strategy 3: Find paragraph boundary
	para_break = content.rfind('\n\n', search_start, search_end)
	if para_break > search_start:
		truncate_at = para_break
		truncation_info['truncation_method'] = 'paragraph_break'
		truncation_info['truncate_at'] = truncate_at
		truncation_info['next_start_char'] = start_from + truncate_at
		truncation_info['final_length'] = truncate_at
		return content[:truncate_at], truncation_info

	# Strategy 4: Find sentence boundary (but avoid URLs, decimals)
	# Look for period followed by space and capital letter, or period + newline
	sentence_patterns = [
		r'\. [A-Z]',  # Period + space + capital
		r'\.\n',  # Period + newline
		r'\? ',  # Question mark + space
		r'! ',  # Exclamation + space
	]

	for pattern in sentence_patterns:
		matches = list(re.finditer(pattern, content[max_chars - 500 : max_chars]))
		if matches:
			last_match = matches[-1]
			truncate_at = (max_chars - 500) + last_match.start() + 1
			truncation_info['truncation_method'] = 'sentence_break'
			truncation_info['truncate_at'] = truncate_at
			truncation_info['next_start_char'] = start_from + truncate_at
			truncation_info['final_length'] = truncate_at
			return content[:truncate_at], truncation_info

	# Strategy 5: Fall back to word boundary
	space_pos = content.rfind(' ', max_chars - 100, max_chars)
	if space_pos > 0:
		truncate_at = space_pos
		truncation_info['truncation_method'] = 'word_break'
	else:
		truncate_at = max_chars
		truncation_info['truncation_method'] = 'hard_limit'

	truncation_info['truncate_at'] = truncate_at
	truncation_info['next_start_char'] = start_from + truncate_at
	truncation_info['final_length'] = truncate_at

	return content[:truncate_at], truncation_info
