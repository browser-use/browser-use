"""Regression tests for the Rect coordinate contract.

Rect documents itself as a closed axis-aligned rectangle with (x1, y1) as the
bottom-left corner and (x2, y2) as the top-right corner. The __post_init__ guard
that enforces this used to `return False`, which dataclasses discard, so inverted
rectangles were accepted and silently changed RectUnionPure.contains() verdicts --
the value that decides whether a node is hidden from the LLM as paint-order occluded.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from browser_use.dom.serializer.paint_order import PaintOrderRemover, Rect


def test_rect_rejects_inverted_x():
	with pytest.raises(ValueError):
		Rect(x1=10, y1=0, x2=5, y2=5)


def test_rect_rejects_inverted_y():
	with pytest.raises(ValueError):
		Rect(x1=0, y1=10, x2=5, y2=5)


def test_rect_accepts_ordered_and_degenerate_coordinates():
	assert Rect(x1=0, y1=0, x2=0, y2=0).area() == 0
	assert Rect(x1=2, y1=2, x2=4, y2=4).area() == 4


def _node(paint_order=None, bounds=None, session_id='sess') -> Any:
	"""Minimal stand-in for SimplifiedNode covering only what calculate_paint_order touches."""
	snapshot_node = None
	if paint_order is not None:
		snapshot_node = SimpleNamespace(paint_order=paint_order, bounds=bounds, computed_styles=None)
	original_node = SimpleNamespace(session_id=session_id, parent_node=None, snapshot_node=snapshot_node)
	return SimpleNamespace(original_node=original_node, children=[], ignored_by_paint_order=False)


def test_calculate_paint_order_skips_malformed_bounds_instead_of_crashing():
	root = _node()
	occluder = _node(paint_order=3, bounds=SimpleNamespace(x=0, y=0, width=10, height=10))
	covered = _node(paint_order=2, bounds=SimpleNamespace(x=1, y=1, width=8, height=8))
	negative_width = _node(paint_order=3, bounds=SimpleNamespace(x=0, y=0, width=-5, height=10))
	nan_width = _node(paint_order=3, bounds=SimpleNamespace(x=0, y=0, width=float('nan'), height=10))
	root.children = [occluder, covered, negative_width, nan_width]

	PaintOrderRemover(root).calculate_paint_order()

	assert covered.ignored_by_paint_order is True
	assert occluder.ignored_by_paint_order is False
	assert negative_width.ignored_by_paint_order is False
	assert nan_width.ignored_by_paint_order is False
