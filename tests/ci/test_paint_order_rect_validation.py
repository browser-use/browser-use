"""Regression tests for the Rect coordinate contract.

Rect documents itself as a closed axis-aligned rectangle with (x1, y1) as the
bottom-left corner and (x2, y2) as the top-right corner. The __post_init__ guard
that enforces this used to `return False`, which dataclasses discard, so inverted
rectangles were accepted and silently changed RectUnionPure.contains() verdicts --
the value that decides whether a node is hidden from the LLM as paint-order occluded.
"""

import pytest

from browser_use.dom.serializer.paint_order import Rect


def test_rect_rejects_inverted_x():
	with pytest.raises(ValueError):
		Rect(x1=10, y1=0, x2=5, y2=5)


def test_rect_rejects_inverted_y():
	with pytest.raises(ValueError):
		Rect(x1=0, y1=10, x2=5, y2=5)


def test_rect_accepts_ordered_and_degenerate_coordinates():
	assert Rect(x1=0, y1=0, x2=0, y2=0).area() == 0
	assert Rect(x1=2, y1=2, x2=4, y2=4).area() == 4
