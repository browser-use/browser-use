from browser_use.dom.serializer.clickable_elements import ClickableElementDetector
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType


def _element_with_bounds(attributes: dict[str, str], width: float, height: float) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='DIV',
		node_value='',
		attributes=attributes,
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
		children_nodes=None,
		ax_node=None,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=None,
			cursor_style=None,
			bounds=DOMRect(x=0, y=0, width=width, height=height),
			clientRects=None,
			scrollRects=None,
			computed_styles=None,
			paint_order=None,
			stacking_contexts=None,
		),
	)


def test_title_identifies_small_icon_control_as_interactive():
	element = _element_with_bounds({'title': 'Create Test'}, width=24, height=24)

	assert ClickableElementDetector.is_interactive(element)


def test_title_alone_does_not_make_large_container_interactive():
	element = _element_with_bounds({'title': 'Create Test'}, width=240, height=80)

	assert not ClickableElementDetector.is_interactive(element)
