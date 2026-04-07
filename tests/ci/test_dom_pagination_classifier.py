"""Tests for DomService.detect_pagination_buttons classification.

Regression for https://github.com/browser-use/browser-use/issues/4620 — when
`«` and `»` are shared between first/last and prev/next pattern lists, buttons
labelled as `aria-label="First page"` / `"Last page"` (with the glyph as the
visible text) used to misclassify as `prev`/`next`. The classifier now matches
specific intents (first/last word patterns) before generic prev/next so semantic
labels win over shared glyphs.
"""

from types import SimpleNamespace
from typing import Any

from browser_use.dom.service import DomService


def _node(
	*,
	text: str = '',
	aria_label: str = '',
	title: str = '',
	class_name: str = '',
	role: str = '',
	xpath: str = '/html/body/button',
	is_clickable: bool = True,
	disabled: str | None = None,
) -> Any:
	"""Build a minimal stand-in for EnhancedDOMTreeNode that satisfies the
	attributes touched by ``DomService.detect_pagination_buttons``.

	The classifier only reads ``snapshot_node.is_clickable``, ``attributes``,
	``xpath``, and ``get_all_children_text()`` — so a SimpleNamespace with the
	right shape is enough and avoids depending on the heavy CDP-backed dataclass.
	"""
	attributes: dict[str, str] = {}
	if aria_label:
		attributes['aria-label'] = aria_label
	if title:
		attributes['title'] = title
	if class_name:
		attributes['class'] = class_name
	if role:
		attributes['role'] = role
	if disabled is not None:
		attributes['disabled'] = disabled

	return SimpleNamespace(
		snapshot_node=SimpleNamespace(is_clickable=is_clickable),
		attributes=attributes,
		xpath=xpath,
		get_all_children_text=lambda t=text: t,
	)


def _classify_one(node: Any) -> str | None:
	"""Run the classifier against a single node and return its button_type."""
	results = DomService.detect_pagination_buttons({1: node})
	if not results:
		return None
	return results[0]['button_type']  # type: ignore[return-value]


# ─── Issue #4620: glyph + semantic label disambiguation ──────────────────────


def test_first_page_glyph_with_aria_label_classifies_as_first():
	"""`«` glyph + ``aria-label='First page'`` must classify as ``first``."""
	node = _node(text='«', aria_label='First page')
	assert _classify_one(node) == 'first'


def test_last_page_glyph_with_aria_label_classifies_as_last():
	"""`»` glyph + ``aria-label='Last page'`` must classify as ``last``."""
	node = _node(text='»', aria_label='Last page')
	assert _classify_one(node) == 'last'


def test_previous_page_with_aria_label_classifies_as_prev():
	"""``aria-label='Previous page'`` should still classify as ``prev``."""
	node = _node(text='‹', aria_label='Previous page')
	assert _classify_one(node) == 'prev'


def test_next_page_with_aria_label_classifies_as_next():
	"""``aria-label='Next page'`` should still classify as ``next``."""
	node = _node(text='›', aria_label='Next page')
	assert _classify_one(node) == 'next'


def test_full_pagination_bar_classifies_each_role_correctly():
	"""End-to-end check across all four roles in a single selector_map.

	This is the exact failing case from issue #4620 — before the fix the
	first/last buttons collapsed onto prev/next.
	"""
	selector_map = {
		1: _node(text='«', aria_label='First page', xpath='/button[1]'),
		2: _node(text='‹', aria_label='Previous page', xpath='/button[2]'),
		3: _node(text='›', aria_label='Next page', xpath='/button[3]'),
		4: _node(text='»', aria_label='Last page', xpath='/button[4]'),
	}
	results = DomService.detect_pagination_buttons(selector_map)
	by_id = {entry['backend_node_id']: entry['button_type'] for entry in results}
	assert by_id == {1: 'first', 2: 'prev', 3: 'next', 4: 'last'}


# ─── Regression: glyph-only buttons preserve legacy fallback ─────────────────


def test_lone_left_guillemet_falls_back_to_prev():
	"""``«`` with no semantic label keeps the historical fallback ``prev``."""
	node = _node(text='«')
	assert _classify_one(node) == 'prev'


def test_lone_right_guillemet_falls_back_to_next():
	"""``»`` with no semantic label keeps the historical fallback ``next``."""
	node = _node(text='»')
	assert _classify_one(node) == 'next'


def test_lone_left_arrow_falls_back_to_prev():
	"""``←`` symbol resolves to ``prev`` (unchanged behaviour)."""
	node = _node(text='←')
	assert _classify_one(node) == 'prev'


def test_lone_right_arrow_falls_back_to_next():
	"""``→`` symbol resolves to ``next`` (unchanged behaviour)."""
	node = _node(text='→')
	assert _classify_one(node) == 'next'


# ─── Regression: localized words and numeric pages still work ────────────────


def test_localized_first_word_classifies_as_first():
	"""Localized ``primera`` (Spanish "first") still classifies as first."""
	node = _node(aria_label='primera página')
	assert _classify_one(node) == 'first'


def test_localized_last_word_classifies_as_last():
	"""Localized ``última`` (Spanish "last") still classifies as last."""
	node = _node(aria_label='última página')
	assert _classify_one(node) == 'last'


def test_numeric_page_button_classifies_as_page_number():
	"""Plain numeric labels (1-99) on a button/link role classify as page_number."""
	node = _node(text='3', role='button')
	assert _classify_one(node) == 'page_number'


def test_non_clickable_node_is_skipped():
	"""Non-clickable nodes are filtered out even when their text matches."""
	node = _node(text='»', aria_label='Last page', is_clickable=False)
	assert _classify_one(node) is None


def test_disabled_attribute_is_reported():
	"""``disabled='true'`` is surfaced via the ``is_disabled`` flag."""
	node = _node(text='»', aria_label='Last page', disabled='true')
	results = DomService.detect_pagination_buttons({1: node})
	assert results[0]['is_disabled'] is True
