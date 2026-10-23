"""_optimize_tree must honor the aria-*/pseudo visibility compensation."""

from types import SimpleNamespace
from typing import Any

from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import NodeType, SimplifiedNode


def _leaf(attributes: dict | None) -> SimplifiedNode:
	original: Any = SimpleNamespace(
		snapshot_node=object(),
		is_visible=False,
		is_actually_scrollable=False,
		node_type=NodeType.ELEMENT_NODE,
		tag_name='div',
		attributes=attributes,
	)
	return SimplifiedNode(original_node=original, children=[])


def test_aria_attributed_leaf_is_kept():
	"""Step 1 forces visibility for aria-*/pseudo elements; _optimize_tree
	must repeat that exception or it drops exactly those leaves."""
	serializer = DOMTreeSerializer(root_node=_leaf(None))  # type: ignore[arg-type]
	kept = serializer._optimize_tree(_leaf({'aria-label': 'menu'}))
	assert kept is not None


def test_unattributed_invisible_leaf_is_still_dropped():
	serializer = DOMTreeSerializer(root_node=_leaf(None))  # type: ignore[arg-type]
	assert serializer._optimize_tree(_leaf(None)) is None
