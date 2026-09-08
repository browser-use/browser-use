"""Regression coverage for DOM text and native select visibility.

PaintOrderRemover.calculate_paint_order() correctly computes which nodes are
fully covered by another element painted on top of them (e.g. content
underneath an open modal/dropdown) and marks them `ignored_by_paint_order`.
DOMTreeSerializer.serialize_tree() must respect that flag for TEXT_NODEs, or
covered text still ends up in the DOM string sent to the LLM every step.
"""

from browser_use.dom.serializer.paint_order import PaintOrderRemover
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType, SimplifiedNode


def _make_snapshot(paint_order: int, bounds: DOMRect) -> EnhancedSnapshotNode:
	return EnhancedSnapshotNode(
		is_clickable=None,
		cursor_style=None,
		bounds=bounds,
		clientRects=None,
		scrollRects=None,
		computed_styles={},
		paint_order=paint_order,
		stacking_contexts=None,
	)


def _make_node(node_type: NodeType, node_value: str, snapshot_node: EnhancedSnapshotNode | None) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=node_type,
		node_name='#text' if node_type == NodeType.TEXT_NODE else 'DIV',
		node_value=node_value,
		attributes={},
		is_scrollable=None,
		is_visible=True,
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


class TestPaintOrderTextExclusion:
	def test_text_fully_covered_by_another_element_is_not_serialized(self):
		"""Two text nodes at identical bounds: the lower paint-order one is fully
		covered by the higher paint-order one and must be excluded from the
		LLM-facing DOM string, even though both are individually `is_visible`."""
		bounds = DOMRect(x=0, y=0, width=100, height=20)
		hidden_node = _make_node(NodeType.TEXT_NODE, 'HIDDEN BEHIND MODAL', _make_snapshot(paint_order=1, bounds=bounds))
		top_node = _make_node(NodeType.TEXT_NODE, 'TOP LAYER TEXT', _make_snapshot(paint_order=2, bounds=bounds))

		hidden_simplified = SimplifiedNode(original_node=hidden_node, children=[])
		top_simplified = SimplifiedNode(original_node=top_node, children=[])

		# should_display=False on the wrapper so serialize_tree skips the element
		# line itself and just recurses straight into the two text-node children.
		wrapper = SimplifiedNode(
			original_node=_make_node(NodeType.ELEMENT_NODE, '', None),
			children=[hidden_simplified, top_simplified],
			should_display=False,
		)

		PaintOrderRemover(wrapper).calculate_paint_order()

		# Sanity check: paint-order calculation itself flagged the covered node.
		assert hidden_simplified.ignored_by_paint_order is True
		assert top_simplified.ignored_by_paint_order is False

		output = DOMTreeSerializer.serialize_tree(wrapper, [])

		assert 'TOP LAYER TEXT' in output
		assert 'HIDDEN BEHIND MODAL' not in output


class TestSelectStateVisibility:
	def test_occluded_scrollable_select_does_not_expose_selected_value(self):
		"""The scrollable-control rendering path must respect paint-order occlusion."""
		bounds = DOMRect(x=0, y=0, width=100, height=20)
		select_snapshot = _make_snapshot(paint_order=1, bounds=bounds)
		select_snapshot.option_selected = False
		select = _make_node(NodeType.ELEMENT_NODE, '', select_snapshot)
		select.node_name = 'SELECT'
		select.attributes = {'id': 'covered-select', 'disabled': ''}
		select.is_scrollable = True
		option_snapshot = _make_snapshot(paint_order=1, bounds=bounds)
		option_snapshot.option_selected = True
		option = _make_node(NodeType.ELEMENT_NODE, '', option_snapshot)
		option.node_name = 'OPTION'
		option.attributes = {'value': 'covered-status', 'label': 'Status behind the overlay'}
		select.children_nodes = [option]
		covered_select = SimplifiedNode(original_node=select, children=[])
		overlay = SimplifiedNode(
			original_node=_make_node(NodeType.TEXT_NODE, 'VISIBLE OVERLAY', _make_snapshot(paint_order=2, bounds=bounds)),
			children=[],
		)
		wrapper = SimplifiedNode(
			original_node=_make_node(NodeType.ELEMENT_NODE, '', None),
			children=[covered_select, overlay],
			should_display=False,
		)

		PaintOrderRemover(wrapper).calculate_paint_order()
		assert covered_select.ignored_by_paint_order is True
		assert select.is_actually_scrollable is True

		output = DOMTreeSerializer.serialize_tree(wrapper, ['id', 'disabled'])

		assert 'VISIBLE OVERLAY' in output
		assert '<select' not in output
		assert 'covered-status' not in output
		assert 'Status behind the overlay' not in output

	def test_indexed_shadow_select_without_snapshot_keeps_unknown_selection(self):
		"""Missing layout must preserve the existing shadow-control action fallback."""
		bounds = DOMRect(x=0, y=0, width=100, height=20)
		host = _make_node(NodeType.ELEMENT_NODE, '', _make_snapshot(paint_order=1, bounds=bounds))
		shadow = _make_node(NodeType.DOCUMENT_FRAGMENT_NODE, '', None)
		shadow.shadow_root_type = 'open'
		shadow.parent_node = host
		host.shadow_roots = [shadow]
		select = _make_node(NodeType.ELEMENT_NODE, '', None)
		select.node_name = 'SELECT'
		select.node_id = 42
		select.backend_node_id = 42
		select.attributes = {'id': 'shadow-select', 'aria-label': 'Choose a status'}
		select.is_visible = False
		select.parent_node = shadow
		shadow.children_nodes = [select]
		option = _make_node(NodeType.ELEMENT_NODE, '', _make_snapshot(paint_order=1, bounds=bounds))
		option.node_name = 'OPTION'
		option.node_id = 43
		option.backend_node_id = 43
		option.attributes = {'value': 'active'}
		option.parent_node = select
		select.children_nodes = [option]

		state = DOMTreeSerializer(host, enable_bbox_filtering=False, paint_order_filtering=False).serialize_accessible_elements()[
			0
		]
		output = state.llm_representation()

		assert state.selector_map[42] is select
		select_line = next(line for line in output.splitlines() if '[42]<select' in line)
		assert 'shadow-select' in select_line
		assert 'selected=unknown' in select_line
		assert 'selected=[]' not in select_line
