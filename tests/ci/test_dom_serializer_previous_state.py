"""Unit tests for DOM serializer previous-state handling (is_new) and hoisted backend_id set."""

from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import (
	DOMRect,
	EnhancedDOMTreeNode,
	EnhancedSnapshotNode,
	NodeType,
	SerializedDOMState,
	SimplifiedNode,
)


def _minimal_snapshot() -> EnhancedSnapshotNode:
	return EnhancedSnapshotNode(
		is_clickable=True,
		cursor_style=None,
		bounds=DOMRect(x=0.0, y=0.0, width=100.0, height=40.0),
		clientRects=None,
		scrollRects=None,
		computed_styles=None,
		paint_order=1,
		stacking_contexts=None,
	)


def _element(
	node_id: int,
	backend_node_id: int,
	tag: str,
	*,
	children: list[EnhancedDOMTreeNode] | None = None,
	snapshot: EnhancedSnapshotNode | None = None,
) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=node_id,
		backend_node_id=backend_node_id,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag.upper(),
		node_value='',
		attributes={} if tag.lower() != 'button' else {'type': 'button'},
		is_scrollable=False,
		is_visible=True,
		absolute_position=None,
		target_id='target-1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=children,
		ax_node=None,
		snapshot_node=snapshot,
	)


def _document(children: list[EnhancedDOMTreeNode]) -> EnhancedDOMTreeNode:
	doc = EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.DOCUMENT_NODE,
		node_name='#document',
		node_value='',
		attributes={},
		is_scrollable=False,
		is_visible=True,
		absolute_position=None,
		target_id='target-1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=children,
		ax_node=None,
		snapshot_node=None,
	)
	for c in children:
		c.parent_node = doc
	return doc


def _two_button_dom() -> tuple[EnhancedDOMTreeNode, EnhancedDOMTreeNode, EnhancedDOMTreeNode]:
	snap = _minimal_snapshot()
	btn_kept = _element(5, 100, 'button', snapshot=snap)
	btn_new = _element(6, 200, 'button', snapshot=snap)
	body = _element(4, 4, 'body', children=[btn_kept, btn_new], snapshot=snap)
	html = _element(3, 3, 'html', children=[body], snapshot=snap)
	btn_kept.parent_node = body
	btn_new.parent_node = body
	body.parent_node = html
	root = _document([html])
	html.parent_node = root
	return root, btn_kept, btn_new


def _collect_interactive_by_backend_id(root: SimplifiedNode | None) -> dict[int, SimplifiedNode]:
	out: dict[int, SimplifiedNode] = {}

	def walk(n: SimplifiedNode) -> None:
		if n.is_interactive:
			out[n.original_node.backend_node_id] = n
		for c in n.children:
			walk(c)

	if root:
		walk(root)
	return out


def test_is_new_with_nonempty_previous_selector_map():
	root, btn_kept, _btn_new = _two_button_dom()
	previous = SerializedDOMState(
		_root=None,
		selector_map={100: btn_kept},
	)
	serializer = DOMTreeSerializer(
		root,
		previous_cached_state=previous,
		enable_bbox_filtering=False,
		paint_order_filtering=False,
	)
	state, _timing = serializer.serialize_accessible_elements()
	assert state._root is not None

	by_backend = _collect_interactive_by_backend_id(state._root)
	assert 100 in by_backend and 200 in by_backend
	assert by_backend[100].is_new is False, 'backend_node_id in previous map should not be is_new'
	assert by_backend[200].is_new is True, 'backend_node_id not in previous map should be is_new'


def test_empty_previous_selector_map_skips_is_new_marking():
	root, _, _ = _two_button_dom()
	previous = SerializedDOMState(_root=None, selector_map={})
	assert not previous.selector_map, 'empty dict must be falsy like production SerializedDOMState'
	serializer = DOMTreeSerializer(
		root,
		previous_cached_state=previous,
		enable_bbox_filtering=False,
		paint_order_filtering=False,
	)
	state, _timing = serializer.serialize_accessible_elements()
	by_backend = _collect_interactive_by_backend_id(state._root)
	assert 100 in by_backend and 200 in by_backend
	assert by_backend[100].is_new is False
	assert by_backend[200].is_new is False
