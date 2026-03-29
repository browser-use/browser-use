"""Snapshot diffing — tracks changes between consecutive DOM snapshots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from browser_use.dom.views import EnhancedDOMTreeNode


class DiffStatus(Enum):
	ADDED = 'added'
	REMOVED = 'removed'
	MODIFIED = 'modified'
	UNCHANGED = 'unchanged'


@dataclass
class ElementDiff:
	backend_node_id: int
	status: DiffStatus


_WHITESPACE_RE = re.compile(r'\s+')


def _canonicalize_text(node: EnhancedDOMTreeNode) -> str:
	"""Lowercase, collapse whitespace, cap at 80 chars."""
	text = node.get_all_children_text(max_depth=2)
	text = _WHITESPACE_RE.sub(' ', text.lower().strip())
	return text[:80]


def _round_bounds(node: EnhancedDOMTreeNode) -> tuple[int, int, int, int] | None:
	"""Round bounds to nearest 2px for comparison."""
	bounds = node.snapshot_node.bounds if node.snapshot_node else None
	if bounds is None:
		return None
	def _r2(v: float) -> int:
		return round(v / 2) * 2
	return (_r2(bounds.x), _r2(bounds.y), _r2(bounds.width), _r2(bounds.height))


def compute_snapshot_diff(
	current_map: dict[int, EnhancedDOMTreeNode],
	previous_map: dict[int, EnhancedDOMTreeNode],
) -> dict[int, ElementDiff]:
	"""Compare current and previous selector maps to detect changes."""
	assert isinstance(current_map, dict), 'current_map must be a dict'
	assert isinstance(previous_map, dict), 'previous_map must be a dict'

	result: dict[int, ElementDiff] = {}

	all_ids = set(current_map.keys()) | set(previous_map.keys())

	for bid in all_ids:
		in_current = bid in current_map
		in_previous = bid in previous_map

		if in_current and not in_previous:
			result[bid] = ElementDiff(backend_node_id=bid, status=DiffStatus.ADDED)
		elif not in_current and in_previous:
			result[bid] = ElementDiff(backend_node_id=bid, status=DiffStatus.REMOVED)
		else:
			# Both present — compare content
			cur_node = current_map[bid]
			prev_node = previous_map[bid]

			text_changed = _canonicalize_text(cur_node) != _canonicalize_text(prev_node)
			bounds_changed = _round_bounds(cur_node) != _round_bounds(prev_node)

			if text_changed or bounds_changed:
				result[bid] = ElementDiff(backend_node_id=bid, status=DiffStatus.MODIFIED)
			else:
				result[bid] = ElementDiff(backend_node_id=bid, status=DiffStatus.UNCHANGED)

	return result
