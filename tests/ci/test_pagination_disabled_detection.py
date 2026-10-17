"""Regression coverage for pagination button disabled-state detection.

CDP's DOM.getDocument parses HTML boolean attributes (e.g. ``<button disabled>``)
as empty strings rather than ``'true'``, so disabled detection must treat the
*presence* of the ``disabled`` attribute as disabled.
"""

from typing import Any

from browser_use.dom.service import DomService
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, EnhancedSnapshotNode, NodeType


def _pagination_node(
	*,
	backend_node_id: int,
	text: str = 'Next',
	attributes: dict[str, str] | None = None,
	tag: str = 'BUTTON',
) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=backend_node_id,
		backend_node_id=backend_node_id,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag,
		node_value='',
		attributes=attributes or {},
		is_scrollable=False,
		is_visible=True,
		absolute_position=DOMRect(x=0, y=0, width=100, height=30),
		target_id='target-1',
		frame_id=None,
		session_id='main',
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=[],
		ax_node=None,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=True,
			cursor_style='pointer',
			bounds=DOMRect(x=0, y=0, width=100, height=30),
			clientRects=DOMRect(x=0, y=0, width=100, height=30),
			scrollRects=None,
			computed_styles={
				'display': 'block',
				'visibility': 'visible',
				'opacity': '1',
				'background-color': 'rgba(0, 0, 0, 0)',
			},
			paint_order=None,
			stacking_contexts=None,
		),
	)


def _children_text(node: EnhancedDOMTreeNode) -> str:
	return ' '.join(
		child.node_value for child in node.children_nodes if child.node_type == NodeType.TEXT_NODE and child.node_value
	)


# EnhancedDOMTreeNode.get_all_children_text() walks children; wire our text in via
# a text-node child so the real production method is exercised.
def _with_text(node: EnhancedDOMTreeNode, text: str) -> EnhancedDOMTreeNode:
	text_node = EnhancedDOMTreeNode(
		node_id=node.node_id + 1000,
		backend_node_id=node.backend_node_id + 1000,
		node_type=NodeType.TEXT_NODE,
		node_name='#text',
		node_value=text,
		attributes={},
		is_scrollable=False,
		is_visible=True,
		absolute_position=None,
		target_id=node.target_id,
		frame_id=None,
		session_id=node.session_id,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=node,
		children_nodes=[],
		ax_node=None,
		snapshot_node=None,
	)
	node.children_nodes = [text_node]
	return node


def _detect(nodes: list[EnhancedDOMTreeNode]) -> list[dict[str, Any]]:
	selector_map = {i: node for i, node in enumerate(nodes, start=1)}
	return DomService.detect_pagination_buttons(selector_map)


def test_native_disabled_attribute_empty_string_is_disabled():
	"""<button disabled>Next</button> — CDP yields attributes={'disabled': ''}."""
	node = _with_text(
		_pagination_node(backend_node_id=1, attributes={'disabled': ''}),
		'Next',
	)
	buttons = _detect([node])
	assert len(buttons) == 1
	assert buttons[0]['button_type'] == 'next'
	assert buttons[0]['is_disabled'] is True


def test_disabled_attribute_with_true_value_is_disabled():
	"""<button disabled="true"> keeps an explicit string value."""
	node = _with_text(
		_pagination_node(backend_node_id=1, attributes={'disabled': 'true'}),
		'Next',
	)
	buttons = _detect([node])
	assert buttons[0]['is_disabled'] is True


def test_aria_disabled_true_is_disabled():
	node = _with_text(
		_pagination_node(backend_node_id=1, attributes={'aria-disabled': 'true'}),
		'Next',
	)
	buttons = _detect([node])
	assert buttons[0]['is_disabled'] is True


def test_aria_disabled_empty_string_is_not_disabled():
	"""aria-disabled='' is ambiguous per the ARIA spec — do not treat as disabled."""
	node = _with_text(
		_pagination_node(backend_node_id=1, attributes={'aria-disabled': ''}),
		'Next',
	)
	buttons = _detect([node])
	assert buttons[0]['is_disabled'] is False


def test_enabled_button_is_not_disabled():
	node = _with_text(_pagination_node(backend_node_id=1), 'Next')
	buttons = _detect([node])
	assert buttons[0]['is_disabled'] is False


def test_disabled_attribute_on_anchor_is_inert():
	"""The native `disabled` attribute is inert on non-form elements per HTML:
	<a disabled> still navigates, so it must NOT be reported as disabled."""
	node = _with_text(
		_pagination_node(backend_node_id=1, attributes={'disabled': ''}, tag='A'),
		'Next',
	)
	buttons = _detect([node])
	assert buttons[0]['is_disabled'] is False


def test_disabled_attribute_on_div_is_inert():
	"""<div disabled> is a common (invalid) authoring pattern; the attribute has
	no HTML semantics there, so only aria-disabled / class-based signals count."""
	node = _with_text(
		_pagination_node(backend_node_id=1, attributes={'disabled': ''}, tag='DIV'),
		'Next',
	)
	buttons = _detect([node])
	assert buttons[0]['is_disabled'] is False


def test_aria_disabled_on_anchor_still_counts():
	"""aria-disabled is element-agnostic — it applies to links too."""
	node = _with_text(
		_pagination_node(backend_node_id=1, attributes={'aria-disabled': 'true'}, tag='A'),
		'Next',
	)
	buttons = _detect([node])
	assert buttons[0]['is_disabled'] is True


def test_disabled_attribute_on_input_is_disabled():
	"""<input disabled> is a form control — presence still means disabled."""
	node = _with_text(
		_pagination_node(backend_node_id=1, attributes={'disabled': ''}, tag='INPUT'),
		'Next',
	)
	buttons = _detect([node])
	assert buttons[0]['is_disabled'] is True
