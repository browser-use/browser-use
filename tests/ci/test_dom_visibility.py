"""Tests for DomService.is_element_visible_according_to_all_parents.

Regression tests for the in-place mutation of shared snapshot bounds: the
visibility check must never modify node.snapshot_node.bounds, and a frame
node must not be transformed by its own bounds when it appears in its own
frame chain (as built by _construct_enhanced_node).
"""

from browser_use.dom.service import DomService, _is_cross_origin_iframe_size_eligible
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType


def _make_snapshot(
	bounds: DOMRect | None = None,
	client_rects: DOMRect | None = None,
	scroll_rects: DOMRect | None = None,
) -> EnhancedSnapshotNode:
	return EnhancedSnapshotNode(
		is_clickable=None,
		cursor_style=None,
		bounds=bounds,
		clientRects=client_rects,
		scrollRects=scroll_rects,
		computed_styles={},
		paint_order=None,
		stacking_contexts=None,
	)


def _make_node(node_name: str, snapshot_node: EnhancedSnapshotNode | None) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name=node_name,
		node_value='',
		attributes={},
		is_scrollable=None,
		is_visible=None,
		absolute_position=None,
		target_id='test-target',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=None,
		ax_node=None,
		snapshot_node=snapshot_node,
	)


def _make_html_frame(viewport_width: float = 1280, viewport_height: float = 900, scroll_y: float = 0) -> EnhancedDOMTreeNode:
	return _make_node(
		'HTML',
		_make_snapshot(
			bounds=DOMRect(x=0, y=0, width=viewport_width, height=viewport_height),
			client_rects=DOMRect(x=0, y=0, width=viewport_width, height=viewport_height),
			scroll_rects=DOMRect(x=0, y=scroll_y, width=viewport_width, height=5000),
		),
	)


class TestVisibilityDoesNotMutateBounds:
	def test_bounds_unchanged_after_visibility_check(self):
		"""The check must not modify the shared snapshot bounds object."""
		html = _make_html_frame(scroll_y=100)
		element = _make_node('DIV', _make_snapshot(bounds=DOMRect(x=10, y=500, width=100, height=50)))

		DomService.is_element_visible_according_to_all_parents(element, [html], viewport_threshold=1000)

		assert element.snapshot_node is not None and element.snapshot_node.bounds is not None
		assert element.snapshot_node.bounds.x == 10
		assert element.snapshot_node.bounds.y == 500

	def test_visibility_check_is_idempotent(self):
		"""Calling the check twice must return the same result (fails if bounds drift)."""
		html = _make_html_frame(viewport_height=900, scroll_y=1000)
		# Element exactly inside the top threshold window: with in-place mutation
		# the first check returns True, then the drifted second check returns False.
		element = _make_node('DIV', _make_snapshot(bounds=DOMRect(x=10, y=0, width=100, height=50)))

		first = DomService.is_element_visible_according_to_all_parents(element, [html], viewport_threshold=1000)
		second = DomService.is_element_visible_according_to_all_parents(element, [html], viewport_threshold=1000)

		assert first is True
		assert second is True

	def test_iframe_not_double_transformed_by_own_bounds(self):
		"""An iframe checked against a frame chain containing itself must not have its
		coordinates doubled (y=1200 on a 900px viewport with threshold 1000 is visible;
		doubled to 2400 it would not be)."""
		html = _make_html_frame(viewport_height=900, scroll_y=0)
		iframe = _make_node('IFRAME', _make_snapshot(bounds=DOMRect(x=0, y=1200, width=600, height=400)))

		# _construct_enhanced_node appends the iframe to its own frame chain before
		# computing its visibility — reproduce that here.
		visible = DomService.is_element_visible_according_to_all_parents(iframe, [html, iframe], viewport_threshold=1000)

		assert visible is True
		assert iframe.snapshot_node is not None and iframe.snapshot_node.bounds is not None
		assert iframe.snapshot_node.bounds.y == 1200


class TestCrossOriginIframeSizeEligibility:
	def test_accepts_wide_secure_card_field(self):
		"""Hosted card fields are often only 40px tall but have enough area to be interactive."""
		assert _is_cross_origin_iframe_size_eligible(width=250, height=40) is True

	def test_accepts_compact_secure_cvv_field(self):
		"""A compact CVV frame must not be dropped solely because both edges are below 50px."""
		assert _is_cross_origin_iframe_size_eligible(width=90, height=40) is True

	def test_rejects_tiny_tracking_frame(self):
		"""Pixel-sized web beacons and one-pixel strips must stay excluded."""
		assert _is_cross_origin_iframe_size_eligible(width=1, height=1) is False
		assert _is_cross_origin_iframe_size_eligible(width=1, height=2500) is False

	def test_accepts_exact_minimum_size(self):
		assert _is_cross_origin_iframe_size_eligible(width=10, height=10) is True

	def test_accepts_native_checkbox_sized_frame(self):
		"""Chromium renders an unstyled native checkbox at roughly 13x13 CSS pixels."""
		assert _is_cross_origin_iframe_size_eligible(width=13, height=13) is True

	def test_rejects_frames_below_the_minimum_edge(self):
		assert _is_cross_origin_iframe_size_eligible(width=9, height=100) is False
		assert _is_cross_origin_iframe_size_eligible(width=100, height=9) is False
