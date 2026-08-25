"""Regression coverage for CDP node identity across iframe sessions."""

from browser_use.dom.serializer.paint_order import PaintOrderRemover
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType, SimplifiedNode


def _node(
	tag_name: str,
	*,
	node_id: int,
	backend_node_id: int,
	session_id: str,
	paint_order: int | None = None,
	background_color: str = 'rgba(0, 0, 0, 0)',
) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=node_id,
		backend_node_id=backend_node_id,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag_name.upper(),
		node_value='',
		attributes={},
		is_scrollable=False,
		is_visible=True,
		absolute_position=DOMRect(x=0, y=0, width=100, height=30),
		target_id=f'target-{session_id}',
		frame_id=None,
		session_id=session_id,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=[],
		ax_node=None,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=None,
			cursor_style='auto',
			bounds=DOMRect(x=0, y=0, width=100, height=30),
			clientRects=DOMRect(x=0, y=0, width=100, height=30),
			scrollRects=None,
			computed_styles={
				'display': 'block',
				'visibility': 'visible',
				'opacity': '1',
				'background-color': background_color,
			},
			paint_order=paint_order,
			stacking_contexts=None,
		),
	)


def test_clickability_cache_scopes_node_ids_to_cdp_session():
	"""A main-page node must not poison an iframe input with the same CDP node ID."""
	non_interactive = _node('div', node_id=7, backend_node_id=20, session_id='main')
	iframe_input = _node('input', node_id=7, backend_node_id=21, session_id='iframe')
	root = _node('html', node_id=100, backend_node_id=100, session_id='main')
	root.children_nodes = [non_interactive, iframe_input]
	non_interactive.parent_node = root
	iframe_input.parent_node = root

	serialized_state = DOMTreeSerializer(
		root,
		enable_bbox_filtering=False,
		paint_order_filtering=False,
	).serialize_accessible_elements()[0]

	assert list(serialized_state.selector_map.values()) == [iframe_input]
	assert '[21]<input' in serialized_state.llm_representation()


def test_paint_order_filtering_is_isolated_between_iframe_documents():
	"""Sibling iframe-local rectangles cannot occlude each other."""
	card_frame = _node('iframe', node_id=10, backend_node_id=10, session_id='wrapper')
	card_frame.frame_id = 'card-frame'
	cvv_frame = _node('iframe', node_id=11, backend_node_id=11, session_id='wrapper')
	cvv_frame.frame_id = 'cvv-frame'
	card_input = _node(
		'input',
		node_id=1,
		backend_node_id=1,
		session_id='wrapper',
		paint_order=1,
		background_color='rgb(255, 255, 255)',
	)
	cvv_input = _node(
		'input',
		node_id=2,
		backend_node_id=2,
		session_id='wrapper',
		paint_order=2,
		background_color='rgb(255, 255, 255)',
	)
	card_input.parent_node = card_frame
	cvv_input.parent_node = cvv_frame
	root = SimplifiedNode(
		original_node=_node('html', node_id=100, backend_node_id=100, session_id='main'),
		children=[
			SimplifiedNode(original_node=card_input, children=[]),
			SimplifiedNode(original_node=cvv_input, children=[]),
		],
	)

	PaintOrderRemover(root).calculate_paint_order()

	assert root.children[0].ignored_by_paint_order is False
	assert root.children[1].ignored_by_paint_order is False


def test_paint_order_filtering_still_applies_within_one_document():
	"""A higher opaque sibling still occludes the same rectangle in its document."""
	lower_input = _node(
		'input',
		node_id=1,
		backend_node_id=1,
		session_id='main',
		paint_order=1,
		background_color='rgb(255, 255, 255)',
	)
	upper_input = _node(
		'input',
		node_id=2,
		backend_node_id=2,
		session_id='main',
		paint_order=2,
		background_color='rgb(255, 255, 255)',
	)
	root = SimplifiedNode(
		original_node=_node('html', node_id=100, backend_node_id=100, session_id='main'),
		children=[
			SimplifiedNode(original_node=lower_input, children=[]),
			SimplifiedNode(original_node=upper_input, children=[]),
		],
	)

	PaintOrderRemover(root).calculate_paint_order()

	assert root.children[0].ignored_by_paint_order is True
	assert root.children[1].ignored_by_paint_order is False
