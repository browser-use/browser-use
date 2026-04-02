"""Tests for EnhancedDOMTreeNode._get_element_position (xpath sibling index)."""

from browser_use.dom.views import EnhancedDOMTreeNode, NodeType


def _el(
	node_id: int,
	backend_node_id: int,
	tag: str,
	*,
	parent: EnhancedDOMTreeNode | None = None,
	children: list[EnhancedDOMTreeNode] | None = None,
) -> EnhancedDOMTreeNode:
	n = EnhancedDOMTreeNode(
		node_id=node_id,
		backend_node_id=backend_node_id,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag.upper(),
		node_value='',
		attributes={},
		is_scrollable=False,
		is_visible=True,
		absolute_position=None,
		target_id='t1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=parent,
		children_nodes=children,
		ax_node=None,
		snapshot_node=None,
	)
	return n


def test_single_same_tag_sibling_returns_zero():
	body = _el(1, 1, 'body', children=[])
	btn = _el(2, 2, 'button', parent=body)
	body.children_nodes = [btn]
	assert btn._get_element_position(btn) == 0


def test_two_same_tag_siblings_one_based_indices():
	body = _el(1, 1, 'body', children=[])
	a = _el(2, 2, 'div', parent=body)
	b = _el(3, 3, 'div', parent=body)
	body.children_nodes = [a, b]
	assert a._get_element_position(a) == 1
	assert b._get_element_position(b) == 2


def test_position_skips_non_element_and_other_tags():
	body = _el(1, 1, 'body', children=[])
	span = _el(2, 2, 'span', parent=body)
	a = _el(3, 3, 'div', parent=body)
	b = _el(4, 4, 'div', parent=body)
	body.children_nodes = [span, a, b]
	assert a._get_element_position(a) == 1
	assert b._get_element_position(b) == 2


def test_element_not_in_parent_children_returns_zero():
	body = _el(1, 1, 'body', children=[])
	orphan = _el(9, 9, 'div', parent=body)
	body.children_nodes = []
	assert orphan._get_element_position(orphan) == 0
