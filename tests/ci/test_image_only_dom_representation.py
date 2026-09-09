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
	"""Image-only clickable cards should expose child image context."""
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
			selector_index=201,
		),
		DEFAULT_INCLUDE_ATTRIBUTES,
	)

	assert '[201]<a' in llm_dom
	assert 'acme-bank-primary-card.png' in llm_dom


def test_direct_interactive_image_includes_own_context_in_llm_dom():
	"""A directly clickable image should expose its own sanitized source context."""
	image = _make_element_node(
		221,
		'img',
		{'src': 'https://cdn.example.test/logos/acme-card.png?token=must-not-leak#preview'},
		x=18,
		y=18,
	)

	llm_dom = DOMTreeSerializer.serialize_tree(
		SimplifiedNode(
			original_node=image,
			children=[],
			is_interactive=True,
			selector_index=221,
		),
		DEFAULT_INCLUDE_ATTRIBUTES,
	)

	assert '[221]<img' in llm_dom
	assert 'image_src=acme-card.png' in llm_dom
	assert 'must-not-leak' not in llm_dom


def test_direct_interactive_image_rejects_browser_normalized_data_src():
	"""Data URLs remain hidden when URL parsing ignores control characters in the scheme."""
	image = _make_element_node(
		222,
		'img',
		{'src': '\x00Da\nTa:image/png;base64,must-not-leak'},
		x=18,
		y=18,
	)

	llm_dom = DOMTreeSerializer.serialize_tree(
		SimplifiedNode(
			original_node=image,
			children=[],
			is_interactive=True,
			selector_index=222,
		),
		DEFAULT_INCLUDE_ATTRIBUTES,
	)

	assert llm_dom == '[222]<img />'
	assert 'must-not-leak' not in llm_dom


def test_direct_interactive_image_omits_oversized_src_context():
	"""Image context does not scan or serialize oversized raw source attributes."""
	image = _make_element_node(
		223,
		'img',
		{'src': f'/{"a" * DOMTreeSerializer.MAX_IMAGE_CONTEXT_ATTRIBUTE_LENGTH}/must-not-leak.png'},
		x=18,
		y=18,
	)

	llm_dom = DOMTreeSerializer.serialize_tree(
		SimplifiedNode(
			original_node=image,
			children=[],
			is_interactive=True,
			selector_index=223,
		),
		DEFAULT_INCLUDE_ATTRIBUTES,
	)

	assert llm_dom == '[223]<img />'
	assert 'must-not-leak' not in llm_dom


def _simplified_image(backend_node_id: int, attributes: dict[str, str]) -> SimplifiedNode:
	image = _make_element_node(backend_node_id, 'img', attributes, x=18, y=18)
	return SimplifiedNode(original_node=image, children=[])


class _NoEagerReverseList(list[SimplifiedNode]):
	def __reversed__(self):
		raise AssertionError('child lists must be traversed lazily')


def test_child_image_context_finds_images_below_non_interactive_wrappers():
	parent = _make_element_node(251, 'a', {'href': '/cards'}, x=10, y=10)
	wrapper = _make_element_node(252, 'div', {}, x=12, y=12)
	node = SimplifiedNode(
		original_node=parent,
		children=[
			SimplifiedNode(
				original_node=wrapper,
				children=[_simplified_image(253, {'src': '/nested-card.png'})],
			),
		],
	)

	context = DOMTreeSerializer._get_child_image_context(node)

	assert context == 'image_src=nested-card.png'


def test_child_image_context_strips_query_and_fragment_without_leaking_query_only_sources():
	parent = _make_element_node(301, 'a', {'href': '/cards'}, x=10, y=10)
	node = SimplifiedNode(
		original_node=parent,
		children=[
			_simplified_image(302, {'src': 'https://cdn.test/card.png?token=secret#preview'}),
			_simplified_image(303, {'src': '?token=must-not-leak'}),
		],
	)

	context = DOMTreeSerializer._get_child_image_context(node)

	assert context == 'image_src=card.png'
	assert 'secret' not in context
	assert 'must-not-leak' not in context


def test_child_image_context_ignores_data_src_but_keeps_accessible_attributes():
	parent = _make_element_node(401, 'button', {}, x=10, y=10)
	node = SimplifiedNode(
		original_node=parent,
		children=[
			_simplified_image(
				402,
				{
					'src': 'data:image/png;base64,private-payload',
					'alt': 'Payment card',
					'title': 'Choose card',
					'aria-label': 'Primary payment method',
				},
			),
		],
	)

	context = DOMTreeSerializer._get_child_image_context(node)

	assert context == 'image_alt=Payment card image_title=Choose card image_label=Primary payment method'
	assert 'data:' not in context
	assert 'private-payload' not in context


def test_child_image_context_limits_returned_images():
	parent = _make_element_node(501, 'a', {'href': '/gallery'}, x=10, y=10)
	node = SimplifiedNode(
		original_node=parent,
		children=[_simplified_image(502 + index, {'src': f'/image-{index}.png'}) for index in range(4)],
	)

	context = DOMTreeSerializer._get_child_image_context(node)

	assert 'image-0.png' in context
	assert 'image-1.png' in context
	assert 'image-2.png' in context
	assert 'image-3.png' not in context


def test_child_image_context_caps_traversal_even_when_images_have_no_context():
	parent = _make_element_node(601, 'a', {'href': '/gallery'}, x=10, y=10)
	ignored_images = [
		_simplified_image(602 + index, {'src': 'data:image/png;base64,ignored'})
		for index in range(DOMTreeSerializer.MAX_CHILD_IMAGE_DESCENDANTS)
	]
	node = SimplifiedNode(
		original_node=parent,
		children=[*ignored_images, _simplified_image(999, {'src': '/too-deep.png'})],
	)

	context = DOMTreeSerializer._get_child_image_context(node)

	assert context == ''


def test_child_image_context_does_not_copy_wide_child_lists_before_traversal():
	parent = _make_element_node(701, 'a', {'href': '/gallery'}, x=10, y=10)
	node = SimplifiedNode(original_node=parent, children=[])
	node.children = _NoEagerReverseList(
		_simplified_image(702 + index, {'src': 'data:image/png;base64,ignored'}) for index in range(200)
	)

	context = DOMTreeSerializer._get_child_image_context(node)

	assert context == ''
