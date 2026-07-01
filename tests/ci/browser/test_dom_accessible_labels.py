from browser_use.dom.serializer.clickable_elements import ClickableElementDetector
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import (
	DEFAULT_INCLUDE_ATTRIBUTES,
	DOMRect,
	EnhancedAXNode,
	EnhancedDOMTreeNode,
	EnhancedSnapshotNode,
	NodeType,
)


def make_element(
	*,
	tag_name: str = 'button',
	attributes: dict[str, str] | None = None,
	ax_name: str | None = None,
	ax_description: str | None = None,
	ax_role: str = 'button',
	width: float = 24,
	height: float = 24,
) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag_name.upper(),
		node_value='',
		attributes=attributes or {},
		is_scrollable=False,
		is_visible=True,
		absolute_position=None,
		target_id='target-id',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=[],
		ax_node=EnhancedAXNode(
			ax_node_id='ax-1',
			ignored=False,
			role=ax_role,
			name=ax_name,
			description=ax_description,
			properties=None,
			child_ids=None,
		),
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


def test_serializer_includes_accessibility_name_and_description_for_icon_only_controls() -> None:
	node = make_element(ax_name='Create Test', ax_description='Opens the create test dialog')

	serialized_attrs = DOMTreeSerializer._build_attributes_string(node, DEFAULT_INCLUDE_ATTRIBUTES, '')

	assert 'ax_name=Create Test' in serialized_attrs
	assert 'ax_description=Opens the create test dialog' in serialized_attrs


def test_meaningful_text_falls_back_to_accessibility_name() -> None:
	node = make_element(ax_name='Create Test')

	assert node.get_meaningful_text_for_llm() == 'Create Test'


def test_small_title_only_icon_is_interactive() -> None:
	node = make_element(
		tag_name='span',
		attributes={'title': 'Create Test'},
		ax_name=None,
		ax_description=None,
		ax_role='generic',
	)

	assert ClickableElementDetector.is_interactive(node)
