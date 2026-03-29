"""Compact flat serialization format for reduced DOM state.

Produces pipe-delimited lines suitable for LLM consumption with
minimal token overhead.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from browser_use.dom.reduction.dominant_group import DominantGroup
from browser_use.dom.reduction.snapshot_diff import DiffStatus, ElementDiff
from browser_use.dom.views import EnhancedDOMTreeNode

_WHITESPACE_RE = re.compile(r'\s+')


def _normalize_text(text: str, max_len: int = 30) -> str:
	"""Collapse whitespace and truncate."""
	text = _WHITESPACE_RE.sub(' ', text.strip())
	if len(text) > max_len:
		text = text[:max_len]
	return text


def _get_role(node: EnhancedDOMTreeNode) -> str:
	"""Get AX role or aria role attribute."""
	# Prefer explicit aria role attribute
	role = (node.attributes or {}).get('role', '')
	if role:
		return role
	# Fall back to AX node role
	if node.ax_node and node.ax_node.role:
		return node.ax_node.role
	return ''


def _get_text(node: EnhancedDOMTreeNode) -> str:
	"""Get display text for element, normalized and truncated."""
	# Try meaningful attributes first
	attrs = node.attributes or {}
	for attr_name in ('value', 'aria-label', 'placeholder', 'title', 'alt'):
		val = attrs.get(attr_name, '')
		if val:
			return _normalize_text(val)
	# Fall back to text content
	text = node.get_all_children_text(max_depth=2)
	return _normalize_text(text)


def _bucket_y(node: EnhancedDOMTreeNode) -> int:
	"""Bucket bounds.y to nearest 200px."""
	bounds = node.snapshot_node.bounds if node.snapshot_node else None
	if bounds is None:
		return 0
	return round(bounds.y / 200) * 200


def _compress_href(href: str, page_url: str | None) -> str:
	"""Compress href for compact display."""
	if not href:
		return ''

	try:
		parsed_href = urlparse(href)
	except Exception:
		return href[:30]

	href_domain = parsed_href.hostname or ''

	# Determine if same domain
	same_domain = False
	if page_url:
		try:
			parsed_page = urlparse(page_url)
			page_domain = parsed_page.hostname or ''
			same_domain = href_domain == page_domain
		except Exception:
			pass

	if same_domain or not href_domain:
		# Same domain or relative URL — compress path
		path = parsed_href.path or ''
		query = parsed_href.query or ''

		# Product page patterns
		for prefix in ('/dp/', '/product/'):
			idx = path.find(prefix)
			if idx >= 0:
				remainder = path[idx + len(prefix):]
				product_id = remainder.split('/')[0]
				return product_id[:30]

		# Search pattern
		if 'search' in path or 'q=' in query:
			return 'search'

		# Cart / checkout
		if 'cart' in path:
			return 'cart'
		if 'checkout' in path:
			return 'checkout'

		# Last path segment
		segments = [s for s in path.rstrip('/').split('/') if s]
		if segments:
			return segments[-1][:30]
		return ''
	else:
		# Different domain — extract second-level domain
		parts = href_domain.split('.')
		if len(parts) >= 2:
			return parts[-2][:10]
		return href_domain[:10]


def serialize_compact(
	selector_map: dict[int, EnhancedDOMTreeNode],
	scores: dict[int, float],
	dominant_group: DominantGroup | None = None,
	diffs: dict[int, ElementDiff] | None = None,
	page_url: str | None = None,
) -> str:
	"""Serialize elements as compact pipe-delimited lines."""
	assert isinstance(selector_map, dict), 'selector_map must be a dict'
	assert isinstance(scores, dict), 'scores must be a dict'

	if not selector_map:
		return ''

	# Build dominant group lookup
	dg_set: set[int] = set()
	dg_order: dict[int, int] = {}  # bid -> 1-based ordinal
	if dominant_group is not None:
		dg_set = set(dominant_group.element_ids)
		for i, bid in enumerate(dominant_group.element_ids):
			dg_order[bid] = i + 1

	# Determine sort order: DG members first (by ordinal), then rest by score desc
	dg_items: list[tuple[int, EnhancedDOMTreeNode]] = []
	non_dg_items: list[tuple[int, EnhancedDOMTreeNode]] = []

	for bid, node in selector_map.items():
		# Skip REMOVED elements when diffs present
		if diffs and bid in diffs and diffs[bid].status == DiffStatus.REMOVED:
			continue
		if bid in dg_set:
			dg_items.append((bid, node))
		else:
			non_dg_items.append((bid, node))

	dg_items.sort(key=lambda kv: dg_order.get(kv[0], 0))
	non_dg_items.sort(key=lambda kv: scores.get(kv[0], 0.0), reverse=True)

	ordered = dg_items + non_dg_items

	lines: list[str] = [
		'Elements: ID|tag|role|text|score|docY|ord|DG|diff|href',
		'Rules: ordinal->DG=1 then ord asc; otherwise score desc. Use click(ID)/input_text(ID,...).',
	]

	for bid, node in ordered:
		tag = node.tag_name
		role = _get_role(node)
		text = _get_text(node)
		score = f'{scores.get(bid, 0.0):.2f}'
		doc_y = str(_bucket_y(node))
		ordinal = str(dg_order[bid]) if bid in dg_order else '-'
		dg_flag = '1' if bid in dg_set else '0'

		# Diff marker
		diff_marker = ''
		if diffs and bid in diffs:
			status = diffs[bid].status
			if status == DiffStatus.ADDED:
				diff_marker = '+'
			elif status == DiffStatus.MODIFIED:
				diff_marker = '~'
			# UNCHANGED -> empty, REMOVED already filtered

		# Href compression
		href = _compress_href((node.attributes or {}).get('href', ''), page_url)

		line = f'{bid}|{tag}|{role}|{text}|{score}|{doc_y}|{ordinal}|{dg_flag}|{diff_marker}|{href}'
		lines.append(line)

	return '\n'.join(lines)
