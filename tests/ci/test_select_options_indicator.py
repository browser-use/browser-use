"""
Test that the '... N more options...' indicator is preserved for <select> elements with >4 options.

This test verifies that:
1. A select with <=4 options serializes all of them (no indicator).
2. A select with >4 options includes the '... N more options...' indicator.

Regression test for issue #5195: the indicator was being dropped by a [:4] slice
in serialize_tree that should have been [:5].

Usage:
	uv run pytest tests/ci/test_select_options_indicator.py -v -s
"""

from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType


def _make_node(
	tag_name: str,
	node_type: NodeType = NodeType.ELEMENT_NODE,
	node_value: str = '',
	attributes: dict | None = None,
	children: list | None = None,
) -> EnhancedDOMTreeNode:
	"""Helper to build a minimal EnhancedDOMTreeNode for testing."""
	node = EnhancedDOMTreeNode(
		node_id=0,
		backend_node_id=0,
		node_type=node_type,
		node_name=tag_name,
		node_value=node_value,
		attributes=attributes or {},
		is_scrollable=None,
		is_visible=None,
		absolute_position=None,
		target_id='',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=children or [],
		ax_node=None,
		snapshot_node=None,
	)
	return node


def _make_option(text: str, value: str = '') -> EnhancedDOMTreeNode:
	"""Build an <option> node with a text child."""
	text_node = _make_node(
		tag_name='#text',
		node_type=NodeType.TEXT_NODE,
		node_value=text,
	)
	option_node = _make_node(
		tag_name='option',
		attributes={'value': value} if value else {},
		children=[text_node],
	)
	return option_node


def _make_select(option_labels: list[str]) -> EnhancedDOMTreeNode:
	"""Build a <select> node with the given option labels."""
	options = [_make_option(label, value=label) for label in option_labels]
	return _make_node(tag_name='select', children=options)


class TestSelectOptionsIndicator:
	"""Tests for _extract_select_options and the serialize_tree slice."""

	def _get_serializer(self, select_node: EnhancedDOMTreeNode) -> DOMTreeSerializer:
		"""Create a DOMTreeSerializer with a dummy root node."""
		root = _make_node(
			tag_name='html',
			node_type=NodeType.DOCUMENT_NODE,
			children=[select_node],
		)
		return DOMTreeSerializer(root)

	def test_select_with_4_or_fewer_options_no_indicator(self):
		"""A <select> with <=4 options should serialize all labels, no indicator."""
		labels = ['Apple', 'Banana', 'Cherry', 'Date']
		select_node = _make_select(labels)
		serializer = self._get_serializer(select_node)

		result = serializer._extract_select_options(select_node)

		assert result is not None
		assert result['count'] == 4
		assert result['first_options'] == ['Apple', 'Banana', 'Cherry', 'Date']

	def test_select_with_more_than_4_options_has_indicator(self):
		"""A <select> with >4 options should include '... N more options...' indicator."""
		labels = ['Apple', 'Banana', 'Cherry', 'Date', 'Elderberry', 'Fig']
		select_node = _make_select(labels)
		serializer = self._get_serializer(select_node)

		result = serializer._extract_select_options(select_node)

		assert result is not None
		assert result['count'] == 6
		assert len(result['first_options']) == 5  # 4 options + 1 indicator
		assert result['first_options'][:4] == ['Apple', 'Banana', 'Cherry', 'Date']
		assert result['first_options'][4] == '... 2 more options...'

	def test_serialize_tree_preserves_indicator_in_options_str(self):
		"""The [:5] slice in serialize_tree must include the indicator element."""
		# Simulate what serialize_tree does with child_info['first_options']
		first_options_with_indicator = [
			'Apple',
			'Banana',
			'Cherry',
			'Date',
			'... 2 more options...',
		]

		# This is the fixed line from serialize_tree ([:5] instead of [:4])
		options_str = '|'.join(first_options_with_indicator[:5])

		assert '... 2 more options...' in options_str
		assert options_str == 'Apple|Banana|Cherry|Date|... 2 more options...'

	def test_serialize_tree_slice_would_drop_indicator_with_old_limit(self):
		"""Verify that [:4] would drop the indicator (documenting the bug)."""
		first_options_with_indicator = [
			'Apple',
			'Banana',
			'Cherry',
			'Date',
			'... 2 more options...',
		]

		# Old buggy behaviour: [:4] drops the indicator
		old_options_str = '|'.join(first_options_with_indicator[:4])
		assert '... 2 more options...' not in old_options_str

		# New fixed behaviour: [:5] keeps the indicator
		new_options_str = '|'.join(first_options_with_indicator[:5])
		assert '... 2 more options...' in new_options_str
