"""Test for Issue #5041: Preserve explicit empty accessibility names.

When an EnhancedDOMTreeNode has an ax_node with name="" (explicitly empty),
DOMInteractedElement.load_from_enhanced_dom_tree should preserve the empty string
instead of collapsing it to None.
"""


from browser_use.dom.views import DOMInteractedElement, DOMRect, NodeType


class FakeAXNode:
	"""A minimal fake AX node for testing."""

	def __init__(self, name: str | None):
		self.name = name


class FakeSnapshotNode:
	"""A minimal fake snapshot node."""

	def __init__(self):
		self.bounds = DOMRect(x=0, y=0, width=100, height=50)


class FakeEnhancedDOMTreeNode:
	"""A minimal fake EnhancedDOMTreeNode for testing load_from_enhanced_dom_tree."""

	def __init__(self, ax_node: FakeAXNode | None, attributes: dict | None = None):
		self.ax_node = ax_node
		self.node_id = 1
		self.backend_node_id = 1
		self.frame_id = None
		self.node_type = NodeType.ELEMENT_NODE
		self.node_value = ''
		self.node_name = 'DIV'
		self.attributes = attributes or {}
		self.snapshot_node = FakeSnapshotNode()
		self.xpath = 'html/body/div[1]'

	def __hash__(self):
		return 123456

	def compute_stable_hash(self):
		return 123456


def test_ax_name_empty_string_preserved():
	"""ax_name="" should be preserved as empty string, not collapsed to None."""
	fake_ax_node = FakeAXNode(name='')
	fake_tree = FakeEnhancedDOMTreeNode(ax_node=fake_ax_node)

	element = DOMInteractedElement.load_from_enhanced_dom_tree(fake_tree)

	assert element.ax_name == '', f'Empty ax_name should be preserved as "", not {element.ax_name!r}'


def test_ax_name_non_empty_string_preserved():
	"""ax_name="New Contact" should be preserved."""
	fake_ax_node = FakeAXNode(name='New Contact')
	fake_tree = FakeEnhancedDOMTreeNode(ax_node=fake_ax_node)

	element = DOMInteractedElement.load_from_enhanced_dom_tree(fake_tree)

	assert element.ax_name == 'New Contact'


def test_ax_name_none_when_no_ax_node():
	"""ax_name should be None when ax_node is absent."""
	fake_tree = FakeEnhancedDOMTreeNode(ax_node=None)

	element = DOMInteractedElement.load_from_enhanced_dom_tree(fake_tree)

	assert element.ax_name is None


def test_ax_name_none_when_ax_node_name_is_none():
	"""ax_name should be None when ax_node.name is None."""
	fake_ax_node = FakeAXNode(name=None)
	fake_tree = FakeEnhancedDOMTreeNode(ax_node=fake_ax_node)

	element = DOMInteractedElement.load_from_enhanced_dom_tree(fake_tree)

	assert element.ax_name is None


def test_ax_name_whitespace_string_preserved():
	"""ax_name=" " (whitespace) should be preserved as-is."""
	fake_ax_node = FakeAXNode(name=' ')
	fake_tree = FakeEnhancedDOMTreeNode(ax_node=fake_ax_node)

	element = DOMInteractedElement.load_from_enhanced_dom_tree(fake_tree)

	assert element.ax_name == ' '
