"""Tests for empty accessibility name preservation (#5041).

Verifies that ax_node.name="" (explicitly empty ARIA name) is preserved
as "" rather than collapsed to None by implicit truthiness checks.
"""

from unittest.mock import MagicMock

from browser_use.dom.views import DOMInteractedElement, EnhancedDOMTreeNode


class TestEmptyAxNamePreserved:
	"""ax_node.name="" should be preserved, not conflated with None."""

	def _make_tree_node(self, ax_name):
		"""Build a minimal EnhancedDOMTreeNode with a given ax_node.name."""
		node = MagicMock(spec=EnhancedDOMTreeNode)
		node.node_id = 1
		node.backend_node_id = 100
		node.frame_id = 'frame1'
		node.node_type = 1
		node.node_value = None
		node.node_name = 'button'
		node.attributes = {'id': 'btn1'}
		node.parent = None
		node.children = []
		node.is_visible = True
		node.highlight_index = 1
		node.bounds = None

		if ax_name is None:
			node.ax_node = None
		else:
			ax_node = MagicMock()
			ax_node.name = ax_name
			node.ax_node = ax_node

		return node

	def test_empty_string_ax_name_preserved(self):
		"""aria-label='' should result in ax_name='' not None."""
		tree_node = self._make_tree_node('')
		elem = DOMInteractedElement.load_from_enhanced_dom_tree(tree_node)
		assert elem.ax_name == '', f'Expected empty string, got {elem.ax_name!r}'

	def test_none_ax_node_gives_none(self):
		"""No ax_node at all should result in ax_name=None."""
		tree_node = self._make_tree_node(None)
		elem = DOMInteractedElement.load_from_enhanced_dom_tree(tree_node)
		assert elem.ax_name is None

	def test_nonempty_ax_name_preserved(self):
		"""Normal non-empty ax_name should work as before."""
		tree_node = self._make_tree_node('Submit')
		elem = DOMInteractedElement.load_from_enhanced_dom_tree(tree_node)
		assert elem.ax_name == 'Submit'
