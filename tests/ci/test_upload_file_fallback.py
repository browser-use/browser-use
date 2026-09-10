from browser_use.dom.service import EnhancedDOMTreeNode
from browser_use.dom.views import DOMRect, NodeType
from browser_use.tools.service import _find_fallback_file_input_for_upload


def _node(*, is_file_input: bool = True, y: int | None = None) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='INPUT' if is_file_input else 'BUTTON',
		node_value='',
		attributes={'type': 'file'} if is_file_input else {},
		is_scrollable=False,
		is_visible=True,
		absolute_position=DOMRect(x=0, y=y, width=10, height=10) if y is not None else None,
		target_id='target',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=None,
		ax_node=None,
		snapshot_node=None,
	)


def _is_file_input(node: EnhancedDOMTreeNode) -> bool:
	return node.attributes.get('type') == 'file'


def test_upload_file_fallback_prefers_closest_positioned_input():
	far_file_input = _node(y=20)
	near_file_input = _node(y=115)
	selector_map = {
		1: _node(is_file_input=False, y=100),
		2: far_file_input,
		3: near_file_input,
	}

	selected, distance, used_coordinate_less_fallback = _find_fallback_file_input_for_upload(selector_map, 100, _is_file_input)

	assert selected is near_file_input
	assert distance == 15
	assert used_coordinate_less_fallback is False


def test_upload_file_fallback_uses_first_file_input_without_coordinates():
	first_file_input = _node()
	second_file_input = _node()
	selector_map = {
		1: _node(is_file_input=False),
		2: first_file_input,
		3: second_file_input,
	}

	selected, distance, used_coordinate_less_fallback = _find_fallback_file_input_for_upload(selector_map, 100, _is_file_input)

	assert selected is first_file_input
	assert distance is None
	assert used_coordinate_less_fallback is True


def test_upload_file_fallback_returns_none_when_page_has_no_file_input():
	selected, distance, used_coordinate_less_fallback = _find_fallback_file_input_for_upload(
		{1: _node(is_file_input=False, y=100)}, 100, _is_file_input
	)

	assert selected is None
	assert distance is None
	assert used_coordinate_less_fallback is False
