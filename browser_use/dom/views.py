import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from cdp_use.cdp.accessibility.commands import GetFullAXTreeReturns
from cdp_use.cdp.accessibility.types import AXPropertyName
from cdp_use.cdp.dom.commands import GetDocumentReturns
from cdp_use.cdp.dom.types import ShadowRootType
from cdp_use.cdp.domsnapshot.commands import CaptureSnapshotReturns
from cdp_use.cdp.target.types import TargetInfo
from uuid_extensions import uuid7str

from browser_use.dom.utils import cap_text_length

# Serializer types
DEFAULT_INCLUDE_ATTRIBUTES = [
	'title',
	'type',
	'checked',
	'name',
	'role',
	'value',
	'placeholder',
	'data-date-format',
	'alt',
	'aria-label',
	'aria-expanded',
	'data-state',
	'aria-checked',
]


@dataclass
class CurrentPageTargets:
	page_session: TargetInfo
	iframe_sessions: list[TargetInfo]
	"""
	Iframe sessions are ALL the iframes sessions of all the pages (not just the current page)
	"""


@dataclass
class TargetAllTrees:
	snapshot: CaptureSnapshotReturns
	dom_tree: GetDocumentReturns
	ax_tree: GetFullAXTreeReturns
	device_pixel_ratio: float
	cdp_timing: dict[str, float]


@dataclass(slots=True)
class SimplifiedNode:
	"""Simplified tree node for optimization."""

	original_node: 'EnhancedDOMTreeNode'
	children: list['SimplifiedNode']
	should_display: bool = True
	interactive_index: int | None = None

	is_new: bool = False

	def __json__(self) -> dict:
		original_node_json = self.original_node.__json__()
		del original_node_json['children_nodes']
		del original_node_json['shadow_roots']
		return {
			'should_display': self.should_display,
			'interactive_index': self.interactive_index,
			'original_node': original_node_json,
			'children': [c.__json__() for c in self.children],
		}


class NodeType(int, Enum):
	"""DOM node types based on the DOM specification."""

	ELEMENT_NODE = 1
	ATTRIBUTE_NODE = 2
	TEXT_NODE = 3
	CDATA_SECTION_NODE = 4
	ENTITY_REFERENCE_NODE = 5
	ENTITY_NODE = 6
	PROCESSING_INSTRUCTION_NODE = 7
	COMMENT_NODE = 8
	DOCUMENT_NODE = 9
	DOCUMENT_TYPE_NODE = 10
	DOCUMENT_FRAGMENT_NODE = 11
	NOTATION_NODE = 12


@dataclass(slots=True)
class DOMRect:
	x: float
	y: float
	width: float
	height: float


@dataclass(slots=True)
class EnhancedAXProperty:
	"""we don't need `sources` and `related_nodes` for now (not sure how to use them)

	TODO: there is probably some way to determine whether it has a value or related nodes or not, but for now it's kinda fine idk
	"""

	name: AXPropertyName
	value: str | bool | None
	# related_nodes: list[EnhancedAXRelatedNode] | None


@dataclass(slots=True)
class EnhancedAXNode:
	ax_node_id: str
	"""Not to be confused the DOM node_id. Only useful for AX node tree"""
	ignored: bool
	# we don't need ignored_reasons as we anyway ignore the node otherwise
	role: str | None
	name: str | None
	description: str | None

	properties: list[EnhancedAXProperty] | None


@dataclass(slots=True)
class EnhancedSnapshotNode:
	"""Snapshot data extracted from DOMSnapshot for enhanced functionality."""

	is_clickable: bool | None
	cursor_style: str | None
	bounds: DOMRect | None
	"""
	Document coordinates (origin = top-left of the page, ignores current scroll).
	Equivalent JS API: layoutNode.boundingBox in the older API.
	Typical use: Quick hit-test that doesn't care about scroll position.
	"""

	clientRects: DOMRect | None
	"""
	Viewport coordinates (origin = top-left of the visible scrollport).
	Equivalent JS API: element.getClientRects() / getBoundingClientRect().
	Typical use: Pixel-perfect hit-testing on screen, taking current scroll into account.
	"""

	scrollRects: DOMRect | None
	"""
	Scrollable area of the element.
	"""

	computed_styles: dict[str, str] | None
	"""Computed styles from the layout tree"""
	paint_order: int | None
	"""Paint order from the layout tree"""
	stacking_contexts: int | None
	"""Stacking contexts from the layout tree"""


# @dataclass(slots=True)
# class SuperSelector:
# 	node_id: int
# 	backend_node_id: int
# 	frame_id: str | None
# 	target_id: str

# 	node_type: NodeType
# 	node_name: str

# 	# is_visible: bool | None
# 	# is_scrollable: bool | None

# 	element_index: int | None


@dataclass(slots=True)
class EnhancedDOMTreeNode:
	"""
	Enhanced DOM tree node that contains information from AX, DOM, and Snapshot trees. It's mostly based on the types on DOM node type with enhanced data from AX and Snapshot trees.

	@dev when serializing check if the value is a valid value first!

	Learn more about the fields:
	- (DOM node) https://chromedevtools.github.io/devtools-protocol/tot/DOM/#type-BackendNode
	- (AX node) https://chromedevtools.github.io/devtools-protocol/tot/Accessibility/#type-AXNode
	- (Snapshot node) https://chromedevtools.github.io/devtools-protocol/tot/DOMSnapshot/#type-DOMNode
	"""

	# region - DOM Node data

	node_id: int
	backend_node_id: int

	node_type: NodeType
	"""Node types, defined in `NodeType` enum."""
	node_name: str
	"""Only applicable for `NodeType.ELEMENT_NODE`"""
	node_value: str
	"""this is where the value from `NodeType.TEXT_NODE` is stored usually"""
	attributes: dict[str, str]
	"""slightly changed from the original attributes to be more readable"""
	is_scrollable: bool | None
	"""
	Whether the node is scrollable.
	"""
	is_visible: bool | None
	"""
	Whether the node is visible according to the upper most frame node.
	"""

	absolute_position: DOMRect | None
	"""
	Absolute position of the node in the document according to the top-left of the page.
	"""

	# frames
	session_id: str | None
	target_id: str
	frame_id: str | None
	content_document: 'EnhancedDOMTreeNode | None'
	"""
	Content document is the document inside a new iframe.
	"""
	# Shadow DOM
	shadow_root_type: ShadowRootType | None
	shadow_roots: list['EnhancedDOMTreeNode'] | None
	"""
	Shadow roots are the shadow DOMs of the element.
	"""

	# Navigation
	parent_node: 'EnhancedDOMTreeNode | None'
	children_nodes: list['EnhancedDOMTreeNode'] | None

	# endregion - DOM Node data

	# region - AX Node data
	ax_node: EnhancedAXNode | None

	# endregion - AX Node data

	# region - Snapshot Node data
	snapshot_node: EnhancedSnapshotNode | None

	# endregion - Snapshot Node data

	# Interactive element index
	element_index: int | None = None

	uuid: str = field(default_factory=uuid7str)

	@property
	def parent(self) -> 'EnhancedDOMTreeNode | None':
		return self.parent_node

	@property
	def children(self) -> list['EnhancedDOMTreeNode']:
		return self.children_nodes or []

	@property
	def children_and_shadow_roots(self) -> list['EnhancedDOMTreeNode']:
		"""
		Returns all children nodes, including shadow roots
		"""
		children = self.children_nodes or []
		if self.shadow_roots:
			children.extend(self.shadow_roots)
		return children

	@property
	def tag_name(self) -> str:
		return self.node_name.lower()

	@property
	def xpath(self) -> str:
		"""Generate XPath for this DOM node, stopping at shadow boundaries or iframes."""
		segments = []
		current_element = self

		while current_element and (
			current_element.node_type == NodeType.ELEMENT_NODE or current_element.node_type == NodeType.DOCUMENT_FRAGMENT_NODE
		):
			# just pass through shadow roots
			if current_element.node_type == NodeType.DOCUMENT_FRAGMENT_NODE:
				current_element = current_element.parent_node
				continue

			# stop ONLY if we hit iframe
			if current_element.parent_node and current_element.parent_node.node_name.lower() == 'iframe':
				break

			position = self._get_element_position(current_element)
			tag_name = current_element.node_name.lower()
			xpath_index = f'[{position}]' if position > 0 else ''
			segments.insert(0, f'{tag_name}{xpath_index}')

			current_element = current_element.parent_node

		return '/'.join(segments)

	def _get_element_position(self, element: 'EnhancedDOMTreeNode') -> int:
		"""Get the position of an element among its siblings with the same tag name.
		Returns 0 if it's the only element of its type, otherwise returns 1-based index."""
		if not element.parent_node or not element.parent_node.children_nodes:
			return 0

		same_tag_siblings = [
			child
			for child in element.parent_node.children_nodes
			if child.node_type == NodeType.ELEMENT_NODE and child.node_name.lower() == element.node_name.lower()
		]

		if len(same_tag_siblings) <= 1:
			return 0  # No index needed if it's the only one

		try:
			# XPath is 1-indexed
			position = same_tag_siblings.index(element) + 1
			return position
		except ValueError:
			return 0

	def __json__(self) -> dict:
		"""Serializes the node and its descendants to a dictionary, omitting parent references."""
		return {
			'node_id': self.node_id,
			'backend_node_id': self.backend_node_id,
			'node_type': self.node_type.name,
			'node_name': self.node_name,
			'node_value': self.node_value,
			'attributes': self.attributes,
			'is_scrollable': self.is_scrollable,
			'session_id': self.session_id,
			'target_id': self.target_id,
			'frame_id': self.frame_id,
			'content_document': self.content_document.__json__() if self.content_document else None,
			'shadow_root_type': self.shadow_root_type,
			'ax_node': asdict(self.ax_node) if self.ax_node else None,
			'snapshot_node': asdict(self.snapshot_node) if self.snapshot_node else None,
			# these two in the end, so it's easier to read json
			'shadow_roots': [r.__json__() for r in self.shadow_roots] if self.shadow_roots else [],
			'children_nodes': [c.__json__() for c in self.children_nodes] if self.children_nodes else [],
		}

	def get_all_children_text(self, max_depth: int = -1) -> str:
		text_parts = []

		def collect_text(node: EnhancedDOMTreeNode, current_depth: int) -> None:
			if max_depth != -1 and current_depth > max_depth:
				return

			# Skip this branch if we hit a highlighted element (except for the current node)
			# TODO: think whether if makese sense to add text until the next clickable element or everything from children
			# if node.node_type == NodeType.ELEMENT_NODE
			# if isinstance(node, DOMElementNode) and node != self and node.highlight_index is not None:
			# 	return

			if node.node_type == NodeType.TEXT_NODE:
				text_parts.append(node.node_value)
			elif node.node_type == NodeType.ELEMENT_NODE:
				for child in node.children:
					collect_text(child, current_depth + 1)

		collect_text(self, 0)
		return '\n'.join(text_parts).strip()

	def __repr__(self) -> str:
		"""
		@DEV ! don't display this to the LLM, it's SUPER long
		"""
		attributes = ', '.join([f'{k}={v}' for k, v in self.attributes.items()])
		is_scrollable = getattr(self, 'is_scrollable', False)
		num_children = len(self.children_nodes or [])
		return (
			f'<{self.tag_name} {attributes} is_scrollable={is_scrollable} '
			f'num_children={num_children} >{self.node_value}</{self.tag_name}>'
		)

	def llm_representation(self, max_text_length: int = 100) -> str:
		"""
		Token friendly representation of the node, used in the LLM
		"""

		return f'<{self.tag_name}>{cap_text_length(self.get_all_children_text(), max_text_length) or ""}'

	@property
	def element_hash(self) -> int:
		return hash(self)

	def __str__(self) -> str:
		return f'[<{self.tag_name}>#{self.frame_id[-4:] if self.frame_id else "?"}:{self.element_index}]'

	def __hash__(self) -> int:
		"""
		Hash the element based on its parent branch path and attributes.

		TODO: migrate this to use only backendNodeId + current SessionId
		"""

		# Get parent branch path
		parent_branch_path = self._get_parent_branch_path()
		parent_branch_path_string = '/'.join(parent_branch_path)

		# Get attributes hash
		attributes_string = ''.join(f'{key}={value}' for key, value in self.attributes.items())

		# Combine both for final hash
		combined_string = f'{parent_branch_path_string}|{attributes_string}'
		element_hash = hashlib.sha256(combined_string.encode()).hexdigest()

		# Convert to int for __hash__ return type - use first 16 chars and convert from hex to int
		return int(element_hash[:16], 16)

	def _get_parent_branch_path(self) -> list[str]:
		"""Get the parent branch path as a list of tag names from root to current element."""
		parents: list['EnhancedDOMTreeNode'] = []
		current_element: 'EnhancedDOMTreeNode | None' = self

		while current_element is not None:
			if current_element.node_type == NodeType.ELEMENT_NODE:
				parents.append(current_element)
			current_element = current_element.parent_node

		parents.reverse()
		return [parent.tag_name for parent in parents]


DOMSelectorMap = dict[int, EnhancedDOMTreeNode]


@dataclass
class SerializedDOMState:
	_root: SimplifiedNode | None
	"""Not meant to be used directly, use `llm_representation` instead"""

	selector_map: DOMSelectorMap

	def llm_representation(
		self,
		include_attributes: list[str] | None = None,
	) -> str:
		"""Kinda ugly, but leaving this as an internal method because include_attributes are a parameter on the agent, so we need to leave it as a 2 step process"""
		from browser_use.dom.serializer.serializer import DOMTreeSerializer

		if not self._root:
			return 'Empty DOM tree (you might have to wait for the page to load)'

		include_attributes = include_attributes or DEFAULT_INCLUDE_ATTRIBUTES

		return DOMTreeSerializer.serialize_tree(self._root, include_attributes)


@dataclass
class DOMInteractedElement:
	"""
	DOMInteractedElement is a class that represents a DOM element that has been interacted with.
	It is used to store the DOM element that has been interacted with and to store the DOM element that has been interacted with.

	TODO: this is a bit of a hack, we should probably have a better way to do this
	"""

	node_id: int
	backend_node_id: int
	frame_id: str | None

	node_type: NodeType
	node_value: str
	node_name: str
	attributes: dict[str, str] | None

	bounds: DOMRect | None

	x_path: str

	element_hash: int

	def to_dict(self) -> dict[str, Any]:
		return {
			'node_type': self.node_type.value,
			'node_value': self.node_value,
			'node_name': self.node_name,
			'attributes': self.attributes,
			'x_path': self.x_path,
		}

	@classmethod
	def load_from_enhanced_dom_tree(cls, enhanced_dom_tree: EnhancedDOMTreeNode) -> 'DOMInteractedElement':
		return cls(
			node_id=enhanced_dom_tree.node_id,
			backend_node_id=enhanced_dom_tree.backend_node_id,
			frame_id=enhanced_dom_tree.frame_id,
			node_type=enhanced_dom_tree.node_type,
			node_value=enhanced_dom_tree.node_value,
			node_name=enhanced_dom_tree.node_name,
			attributes=enhanced_dom_tree.attributes,
			bounds=enhanced_dom_tree.snapshot_node.bounds if enhanced_dom_tree.snapshot_node else None,
			x_path=enhanced_dom_tree.xpath,
			element_hash=hash(enhanced_dom_tree),
		)
