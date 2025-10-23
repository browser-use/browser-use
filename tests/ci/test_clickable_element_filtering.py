import pytest
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType
from browser_use.dom.serializer.clickable_elements import ClickableElementDetector

class DummySnapshotNode:
    def __init__(self, x, y, width, height):
        self.bounds = type('Rect', (), {'x': x, 'y': y, 'width': width, 'height': height})()

@pytest.mark.parametrize("attrs,snapshot,expected", [
    ({'inert': ''}, DummySnapshotNode(10, 10, 100, 20), False),
    ({'aria-hidden': 'true'}, DummySnapshotNode(10, 10, 100, 20), False),
    ({}, DummySnapshotNode(-10, 10, 100, 20), False),
    ({}, DummySnapshotNode(10, 10, 0, 20), False),
    ({}, DummySnapshotNode(10, 10, 100, 0), False),
    ({}, DummySnapshotNode(10, 10, 100, 20), True),
])
def test_clickable_element_filtering(attrs, snapshot, expected):
    node = EnhancedDOMTreeNode(
        node_id=1,
        backend_node_id=1,
        node_type=NodeType.ELEMENT_NODE,
        node_name='button',
        node_value='',
        attributes=attrs,
        is_scrollable=None,
        is_visible=True,
        absolute_position=None,
        target_id=None,
        frame_id=None,
        session_id=None,
        content_document=None,
        shadow_root_type=None,
        shadow_roots=None,
        parent_node=None,
        children_nodes=None,
        ax_node=None,
        snapshot_node=snapshot,
        _compound_children=[],
        uuid='dummy',
    )
    assert ClickableElementDetector.is_interactive(node) == expected
