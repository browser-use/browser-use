"""Tests for DOMInteractedElement.load_from_enhanced_dom_tree ax_name handling.

Regression test for issue #5041: an explicitly empty accessibility name
(e.g. aria-label="") must be preserved as "" on the resulting element, not
collapsed to None. The implicit truthiness check `if ax_node.name:` treated an
empty string the same as a missing value, conflating two distinct states.
"""

from browser_use.dom.views import (
	DOMInteractedElement,
	EnhancedAXNode,
	EnhancedDOMTreeNode,
	EnhancedSnapshotNode,
	NodeType,
)


def _make_ax_node(name: str | None) -> EnhancedAXNode:
	return EnhancedAXNode(
		ax_node_id='ax-1',
		ignored=False,
		role='button',
		name=name,
		description=None,
		properties=None,
		child_ids=None,
	)


def _make_node(ax_node: EnhancedAXNode | None) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='BUTTON',
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
		ax_node=ax_node,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=None,
			cursor_style=None,
			bounds=None,
			clientRects=None,
			scrollRects=None,
			computed_styles={},
			paint_order=None,
			stacking_contexts=None,
		),
	)


class TestLoadFromEnhancedDomTreeAxName:
	def test_non_empty_ax_name_is_preserved(self):
		node = _make_node(_make_ax_node('Submit'))
		element = DOMInteractedElement.load_from_enhanced_dom_tree(node)
		assert element.ax_name == 'Submit'

	def test_explicitly_empty_ax_name_is_preserved_as_empty_string(self):
		"""aria-label="" is a valid, intentional value and must round-trip as ""
		rather than being flattened to None (which means "no name at all")."""
		node = _make_node(_make_ax_node(''))
		element = DOMInteractedElement.load_from_enhanced_dom_tree(node)
		assert element.ax_name == ''

	def test_null_ax_name_yields_none(self):
		"""When the AX node reports name=None the element keeps ax_name=None."""
		node = _make_node(_make_ax_node(None))
		element = DOMInteractedElement.load_from_enhanced_dom_tree(node)
		assert element.ax_name is None

	def test_missing_ax_node_yields_none(self):
		"""No AX node attached at all -> ax_name stays None."""
		node = _make_node(None)
		element = DOMInteractedElement.load_from_enhanced_dom_tree(node)
		assert element.ax_name is None
