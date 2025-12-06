from __future__ import annotations

import re
from typing import Callable

from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.views import EnhancedDOMTreeNode


def _normalize(text: str, case_sensitive: bool) -> str:
	return text if case_sensitive else text.lower()


def text_matches(haystack: str, needle: str, *, case_sensitive: bool = False, partial: bool = True) -> bool:
	if not haystack or needle is None:
		return False
	h_norm = _normalize(haystack, case_sensitive)
	n_norm = _normalize(needle, case_sensitive)
	if partial:
		return n_norm in h_norm
	return h_norm == n_norm


def assert_text_present(page_text: str, expected: str, *, case_sensitive: bool = False, partial: bool = True) -> bool:
	return text_matches(page_text, expected, case_sensitive=case_sensitive, partial=partial)


def assert_text_absent(page_text: str, expected: str, *, case_sensitive: bool = False, partial: bool = True) -> bool:
	return not text_matches(page_text, expected, case_sensitive=case_sensitive, partial=partial)


def _match_with_mode(actual: str, expected: str, mode: str) -> bool:
	if mode == 'equals':
		return actual == expected
	if mode == 'prefix':
		return actual.startswith(expected)
	if mode == 'contains':
		return expected in actual
	if mode == 'regex':
		try:
			pattern = re.compile(expected, re.IGNORECASE)
			if pattern.search(actual):
				return True
			# Fallback for over-escaped patterns (e.g., double backslashes from param passing)
			try:
				fallback = re.compile(expected.encode().decode('unicode_escape'), re.IGNORECASE)
				return fallback.search(actual) is not None
			except Exception:
				return False
		except re.error:
			return False
	return False


def assert_url(summary: BrowserStateSummary, expected: str, match_mode: str = 'equals') -> bool:
	url = summary.url or ''
	return _match_with_mode(url, expected, match_mode)


def assert_title(summary: BrowserStateSummary, expected: str, match_mode: str = 'equals') -> bool:
	title = summary.title or ''
	return _match_with_mode(title, expected, match_mode)


def is_visible_node(node: EnhancedDOMTreeNode | None) -> bool:
	if not node:
		return False
	# Prefer explicit visibility flag when available
	if node.is_visible is False:
		return False
	# Fall back to bounds checks
	bounds = node.snapshot_node.bounds if node.snapshot_node else node.absolute_position
	if not bounds:
		return False
	return bounds.height > 0 and bounds.width > 0


