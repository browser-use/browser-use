from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import (
	DEFAULT_INCLUDE_ATTRIBUTES,
	DOMRect,
	EnhancedDOMTreeNode,
	EnhancedSnapshotNode,
	NodeType,
	SimplifiedNode,
)


def _make_element_node(
	backend_node_id: int,
	tag_name: str,
	attributes: dict[str, str],
	x: float,
	y: float,
	width: float = 64,
	height: float = 64,
	parent: EnhancedDOMTreeNode | None = None,
) -> EnhancedDOMTreeNode:
	bounds = DOMRect(x=x, y=y, width=width, height=height)
	return EnhancedDOMTreeNode(
		node_id=backend_node_id,
		backend_node_id=backend_node_id,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag_name.upper(),
		node_value='',
		attributes=attributes,
		is_scrollable=None,
		is_visible=True,
		absolute_position=bounds,
		target_id='target-1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=parent,
		children_nodes=None,
		ax_node=None,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=tag_name in {'a', 'button'},
			cursor_style='pointer' if tag_name in {'a', 'button'} else None,
			bounds=bounds,
			clientRects=bounds,
			scrollRects=None,
			computed_styles=None,
			paint_order=None,
			stacking_contexts=None,
		),
	)


def test_image_only_interactive_parent_includes_child_image_context_in_llm_dom():
	"""Image-only clickable cards should expose child image context so the LLM can tell options apart."""
	link = _make_element_node(201, 'a', {'href': '/select-payment-method'}, x=10, y=10, width=80, height=80)
	image = _make_element_node(
		202,
		'img',
		{'src': 'https://cdn.example.test/logos/acme-bank-primary-card.png'},
		x=18,
		y=18,
		width=64,
		height=64,
		parent=link,
	)
	link.children_nodes = [image]

	llm_dom = DOMTreeSerializer.serialize_tree(
		SimplifiedNode(
			original_node=link,
			children=[SimplifiedNode(original_node=image, children=[])],
			is_interactive=True,
		),
		DEFAULT_INCLUDE_ATTRIBUTES,
	)

	assert '[201]<a' in llm_dom
	assert 'acme-bank-primary-card.png' in llm_dom
