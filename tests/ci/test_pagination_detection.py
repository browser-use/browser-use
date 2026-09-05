"""Regression coverage for pagination button classification (#5514)."""

from browser_use.dom.service import DomService
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType


def _clickable(
	tag_name: str,
	text: str,
	*,
	node_id: int,
	role: str = '',
	class_name: str = '',
	aria_label: str = '',
	title: str = '',
) -> EnhancedDOMTreeNode:
	bounds = DOMRect(x=0, y=0, width=80, height=28)
	node = EnhancedDOMTreeNode(
		node_id=node_id,
		backend_node_id=node_id,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag_name.upper(),
		node_value='',
		attributes={'role': role, 'class': class_name, 'aria-label': aria_label, 'title': title},
		is_scrollable=False,
		is_visible=True,
		absolute_position=bounds,
		target_id='target-1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=[],
		ax_node=None,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=True,
			cursor_style='pointer',
			bounds=bounds,
			clientRects=bounds,
			scrollRects=None,
			computed_styles={},
			paint_order=None,
			stacking_contexts=None,
		),
	)
	if text:
		text_node = EnhancedDOMTreeNode(
			node_id=node_id + 1000,
			backend_node_id=node_id + 1000,
			node_type=NodeType.TEXT_NODE,
			node_name='#text',
			node_value=text,
			attributes={},
			is_scrollable=False,
			is_visible=True,
			absolute_position=bounds,
			target_id='target-1',
			frame_id=None,
			session_id=None,
			content_document=None,
			shadow_root_type=None,
			shadow_roots=None,
			parent_node=node,
			children_nodes=None,
			ax_node=None,
			snapshot_node=None,
		)
		node.children_nodes = [text_node]
	return node


def _types(buttons: list[dict[str, str | int | bool]]) -> list[tuple[str, str]]:
	return [(str(button['text']), str(button['button_type'])) for button in buttons]


def test_pagination_ignores_css_class_and_substring_false_positives():
	buttons = DomService.detect_pagination_buttons(
		{
			1: _clickable('a', 'Preview', node_id=1, class_name='preview-link'),
			2: _clickable('button', 'Continue', node_id=2, class_name='pagination-next'),
			3: _clickable('button', 'Last name', node_id=3),
			4: _clickable('button', 'Last modified', node_id=4),
			5: _clickable('button', 'Next steps', node_id=5),
			6: _clickable('button', '', node_id=6, aria_label='price < 100'),
		}
	)

	assert buttons == []


def test_pagination_keeps_real_controls_and_decorated_labels():
	buttons = DomService.detect_pagination_buttons(
		{
			1: _clickable('a', 'Next', node_id=1, role='button'),
			2: _clickable('a', '‹ Previous', node_id=2),
			3: _clickable('button', 'Next page', node_id=3),
			4: _clickable('a', '1', node_id=4),
			5: _clickable('a', '2', node_id=5),
			6: _clickable('button', 'First', node_id=6),
			7: _clickable('button', 'Last', node_id=7),
			8: _clickable('button', '>', node_id=8),
		}
	)

	assert _types(buttons) == [
		('Next', 'next'),
		('‹ Previous', 'prev'),
		('Next page', 'next'),
		('1', 'page_number'),
		('2', 'page_number'),
		('First', 'first'),
		('Last', 'last'),
		('>', 'next'),
	]


def test_pagination_rejects_lone_numeric_widgets():
	buttons = DomService.detect_pagination_buttons(
		{
			1: _clickable('button', '5', node_id=1, role='button'),
			2: _clickable('span', '3', node_id=2),
			3: _clickable('div', '10', node_id=3, role=''),
		}
	)

	assert buttons == []
