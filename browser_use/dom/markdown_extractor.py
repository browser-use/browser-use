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
		enhanced_dom_tree = await dom_service.get_dom_tree(target_id=target_id)
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

	# Remove lines that are only whitespace or very short (likely artifacts)
	lines = content.split('\n')
	filtered_lines = []
	for line in lines:
		stripped = line.strip()
		# Keep lines with substantial content
		if len(stripped) > 2:
			# Skip lines that look like JSON (start with { or [ and are very long)
			if (stripped.startswith('{') or stripped.startswith('[')) and len(stripped) > 100:
				continue
			filtered_lines.append(line)

	content = '\n'.join(filtered_lines)
	content = content.strip()

	chars_filtered = original_length - len(content)
	return content, chars_filtered
