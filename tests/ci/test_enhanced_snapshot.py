"""Tests for build_snapshot_lookup parsing of raw CDP DOMSnapshot.captureSnapshot data."""

from typing import Any

from browser_use.dom.enhanced_snapshot import build_snapshot_lookup
from browser_use.dom.views import DOMRect


def _make_snapshot(num_nodes: int, layout_extra: dict[str, Any] | None = None) -> Any:
	"""One document where node i has backendNodeId 100+i and layout node i."""
	layout: dict[str, Any] = {
		'nodeIndex': list(range(num_nodes)),
		'styles': [[] for _ in range(num_nodes)],
		'bounds': [[10, 20, 200, 200] for _ in range(num_nodes)],
		'text': [-1] * num_nodes,
		**(layout_extra or {}),
	}
	return {
		'documents': [
			{
				'documentURL': 0,
				'nodes': {'backendNodeId': [100 + i for i in range(num_nodes)]},
				'layout': layout,
			}
		],
		'strings': ['about:blank'],
	}


class TestStackingContexts:
	def test_sparse_index_is_membership_not_position(self):
		"""stackingContexts is RareBooleanData: `index` lists the layout nodes that create a stacking context."""
		lookup = build_snapshot_lookup(_make_snapshot(4, {'stackingContexts': {'index': [3]}}))

		assert [lookup[100 + i].stacking_contexts for i in range(4)] == [False, False, False, True]

	def test_missing_or_empty_stacking_contexts_is_false(self):
		for layout_extra in ({}, {'stackingContexts': {}}, {'stackingContexts': {'index': []}}):
			lookup = build_snapshot_lookup(_make_snapshot(2, layout_extra))
			assert [lookup[100 + i].stacking_contexts for i in range(2)] == [False, False]


class TestDevicePixelRatio:
	"""Chrome reports bounds in device pixels but clientRects/scrollRects in CSS pixels.

	clientRects/scrollRects come from Element.clientLeft/clientWidth and scrollLeft/scrollWidth,
	which Blink already zoom-adjusts, so only bounds must be divided by the device pixel ratio.
	Verified against Chrome with --force-device-scale-factor=2.
	"""

	def _lookup(self, device_pixel_ratio: float):
		snapshot = _make_snapshot(
			1,
			{
				'clientRects': [[5, 5, 185, 185]],
				'scrollRects': [[11, 70, 600, 900]],
			},
		)
		return build_snapshot_lookup(snapshot, device_pixel_ratio)[100]

	def test_dpr_1_leaves_all_rects_unchanged(self):
		node = self._lookup(1.0)
		assert node.bounds == DOMRect(x=10, y=20, width=200, height=200)
		assert node.clientRects == DOMRect(x=5, y=5, width=185, height=185)
		assert node.scrollRects == DOMRect(x=11, y=70, width=600, height=900)

	def test_dpr_2_scales_bounds_only(self):
		node = self._lookup(2.0)
		assert node.bounds == DOMRect(x=5, y=10, width=100, height=100)
		assert node.clientRects == DOMRect(x=5, y=5, width=185, height=185)
		assert node.scrollRects == DOMRect(x=11, y=70, width=600, height=900)
