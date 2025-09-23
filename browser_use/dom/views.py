import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from cdp_use.cdp.accessibility.commands import GetFullAXTreeReturns
from cdp_use.cdp.accessibility.types import AXPropertyName
from cdp_use.cdp.dom.commands import GetDocumentReturns
from cdp_use.cdp.dom.types import ShadowRootType
from cdp_use.cdp.domsnapshot.commands import CaptureSnapshotReturns
from cdp_use.cdp.target.types import SessionID, TargetID, TargetInfo
from uuid_extensions import uuid7str

from browser_use.dom.utils import cap_text_length
from browser_use.observability import observe_debug

# Serializer types
DEFAULT_INCLUDE_ATTRIBUTES = [
	'title',
	'type',
	'checked',
	# 'class',
	'id',
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
	# ARIA value attributes for datetime/range inputs
	'aria-valuemin',
	'aria-valuemax',
	'aria-valuenow',
	'aria-placeholder',
	# Validation attributes - help agents avoid brute force attempts
	'pattern',
	'min',
	'max',
	'minlength',
	'maxlength',
	'step',
	# Webkit shadow DOM identifiers
	'pseudo',
	# Accessibility properties from ax_node (ordered by importance for automation)
	'checked',
	'selected',
	'expanded',
	'pressed',
	'disabled',
	'invalid',  # Current validation state from AX node
	'valuemin',  # Min value from AX node (for datetime/range)
	'valuemax',  # Max value from AX node (for datetime/range)
	'valuenow',
	'keyshortcuts',
	'haspopup',
	'multiselectable',
	# Less commonly needed (uncomment if required):
	# 'readonly',
	'required',
	'valuetext',
	'level',
	'busy',
	'live',
	# Accessibility name (contains text content for StaticText elements)
	'ax_name',
]

STATIC_ATTRIBUTES = {
	'class',
	'id',
	'name',
	'type',
	'placeholder',
	'aria-label',
	'title',
	# 'aria-expanded',
	'role',
	'data-testid',
	'data-test',
	'data-cy',
	'data-selenium',
	'for',
	'required',
	'disabled',
	'readonly',
	'checked',
	'selected',
	'multiple',
	'href',
	'target',
	'rel',
	'aria-describedby',
	'aria-labelledby',
	'aria-controls',
	'aria-owns',
	'aria-live',
	'aria-atomic',
	'aria-busy',
	'aria-disabled',
	'aria-hidden',
	'aria-pressed',
	'aria-checked',
	'aria-selected',
	'tabindex',
	'alt',
	'src',
	'lang',
	'itemscope',
	'itemtype',
	'itemprop',
	# Webkit shadow DOM attributes
	'pseudo',
	'aria-valuemin',
	'aria-valuemax',
	'aria-valuenow',
	'aria-placeholder',
}


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
class PropagatingBounds:
	"""Track bounds that propagate from parent elements to filter children."""

	tag: str  # The tag that started propagation ('a' or 'button')
	bounds: 'DOMRect'  # The bounding box
	node_id: int  # Node ID for debugging
	depth: int  # How deep in tree this started (for debugging)


@dataclass(slots=True)
class SimplifiedNode:
	"""Simplified tree node for optimization."""

	original_node: 'EnhancedDOMTreeNode'
	children: list['SimplifiedNode']
	should_display: bool = True
	interactive_index: int | None = None

	is_new: bool = False

	ignored_by_paint_order: bool = False  # More info in dom/serializer/paint_order.py
	excluded_by_parent: bool = False  # New field for bbox filtering
	is_shadow_host: bool = False  # New field for shadow DOM hosts
	is_compound_component: bool = False  # True for virtual components of compound controls

	def _clean_original_node_json(self, node_json: dict) -> dict:
		"""Recursively remove children_nodes and shadow_roots from original_node JSON."""
		# Remove the fields we don't want in SimplifiedNode serialization
		if 'children_nodes' in node_json:
			del node_json['children_nodes']
		if 'shadow_roots' in node_json:
			del node_json['shadow_roots']

		# Clean nested content_document if it exists
		if node_json.get('content_document'):
			node_json['content_document'] = self._clean_original_node_json(node_json['content_document'])

		return node_json

	def __json__(self) -> dict:
		original_node_json = self.original_node.__json__()
		# Remove children_nodes and shadow_roots to avoid duplication with SimplifiedNode.children
		cleaned_original_node_json = self._clean_original_node_json(original_node_json)
		return {
			'should_display': self.should_display,
			'interactive_index': self.interactive_index,
			'ignored_by_paint_order': self.ignored_by_paint_order,
			'excluded_by_parent': self.excluded_by_parent,
			'original_node': cleaned_original_node_json,
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

	def to_dict(self) -> dict[str, Any]:
		return {
			'x': self.x,
			'y': self.y,
			'width': self.width,
			'height': self.height,
		}

	def __json__(self) -> dict:
		return self.to_dict()


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
	child_ids: list[str] | None


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
# 	target_id: TargetID

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
	target_id: TargetID
	frame_id: str | None
	session_id: SessionID | None
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

	# Compound control child components information
	_compound_children: list[dict[str, Any]] = field(default_factory=list)

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
			'is_visible': self.is_visible,
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

	def get_meaningful_text_for_llm(self) -> str:
		"""
		Get the meaningful text content that the LLM actually sees for this element.
		This matches exactly what goes into the DOMTreeSerializer output.
		"""
		meaningful_text = ''
		if hasattr(self, 'attributes') and self.attributes:
			# Priority order: value, aria-label, title, placeholder, alt, text content
			for attr in ['value', 'aria-label', 'title', 'placeholder', 'alt']:
				if attr in self.attributes and self.attributes[attr]:
					meaningful_text = self.attributes[attr]
					break

		# Fallback to text content if no meaningful attributes
		if not meaningful_text:
			meaningful_text = self.get_all_children_text()

		return meaningful_text.strip()

	@property
	def is_actually_scrollable(self) -> bool:
		"""
		Enhanced scroll detection that combines CDP detection with CSS analysis.

		This detects scrollable elements that Chrome's CDP might miss, which is common
		in iframes and dynamically sized containers.
		"""
		# First check if CDP already detected it as scrollable
		if self.is_scrollable:
			return True

		# Enhanced detection for elements CDP missed
		if not self.snapshot_node:
			return False

		# Check scroll vs client rects - this is the most reliable indicator
		scroll_rects = self.snapshot_node.scrollRects
		client_rects = self.snapshot_node.clientRects

		if scroll_rects and client_rects:
			# Content is larger than visible area = scrollable
			has_vertical_scroll = scroll_rects.height > client_rects.height + 1  # +1 for rounding
			has_horizontal_scroll = scroll_rects.width > client_rects.width + 1

			if has_vertical_scroll or has_horizontal_scroll:
				# Also check CSS to make sure scrolling is allowed
				if self.snapshot_node.computed_styles:
					styles = self.snapshot_node.computed_styles

					overflow = styles.get('overflow', 'visible').lower()
					overflow_x = styles.get('overflow-x', overflow).lower()
					overflow_y = styles.get('overflow-y', overflow).lower()

					# Only allow scrolling if overflow is explicitly set to auto, scroll, or overlay
					# Do NOT consider 'visible' overflow as scrollable - this was causing the issue
					allows_scroll = (
						overflow in ['auto', 'scroll', 'overlay']
						or overflow_x in ['auto', 'scroll', 'overlay']
						or overflow_y in ['auto', 'scroll', 'overlay']
					)

					return allows_scroll
				else:
					# No CSS info, but content overflows - be more conservative
					# Only consider it scrollable if it's a common scrollable container element
					scrollable_tags = {'div', 'main', 'section', 'article', 'aside', 'body', 'html'}
					return self.tag_name.lower() in scrollable_tags

		return False

	@property
	def should_show_scroll_info(self) -> bool:
		"""
		Simple check: show scroll info only if this element is scrollable
		and doesn't have a scrollable parent (to avoid nested scroll spam).

		Special case for iframes: Always show scroll info since Chrome might not
		always detect iframe scrollability correctly (scrollHeight: 0 issue).
		"""
		# Special case: Always show scroll info for iframe elements
		# Even if not detected as scrollable, they might have scrollable content
		if self.tag_name.lower() == 'iframe':
			return True

		# Must be scrollable first for non-iframe elements
		if not (self.is_scrollable or self.is_actually_scrollable):
			return False

		# Always show for iframe content documents (body/html)
		if self.tag_name.lower() in {'body', 'html'}:
			return True

		# Don't show if parent is already scrollable (avoid nested spam)
		if self.parent_node and (self.parent_node.is_scrollable or self.parent_node.is_actually_scrollable):
			return False

		return True

	def _find_html_in_content_document(self) -> 'EnhancedDOMTreeNode | None':
		"""Find HTML element in iframe content document."""
		if not self.content_document:
			return None

		# Check if content document itself is HTML
		if self.content_document.tag_name.lower() == 'html':
			return self.content_document

		# Look through children for HTML element
		if self.content_document.children_nodes:
			for child in self.content_document.children_nodes:
				if child.tag_name.lower() == 'html':
					return child

		return None

	@property
	def scroll_info(self) -> dict[str, Any] | None:
		"""Calculate scroll information for this element if it's scrollable."""
		if not self.is_actually_scrollable or not self.snapshot_node:
			return None

		# Get scroll and client rects from snapshot data
		scroll_rects = self.snapshot_node.scrollRects
		client_rects = self.snapshot_node.clientRects
		bounds = self.snapshot_node.bounds

		if not scroll_rects or not client_rects:
			return None

		# Calculate scroll position and percentages
		scroll_top = scroll_rects.y
		scroll_left = scroll_rects.x

		# Total scrollable height and width
		scrollable_height = scroll_rects.height
		scrollable_width = scroll_rects.width

		# Visible (client) dimensions
		visible_height = client_rects.height
		visible_width = client_rects.width

		# Calculate how much content is above/below/left/right of current view
		content_above = max(0, scroll_top)
		content_below = max(0, scrollable_height - visible_height - scroll_top)
		content_left = max(0, scroll_left)
		content_right = max(0, scrollable_width - visible_width - scroll_left)

		# Calculate scroll percentages
		vertical_scroll_percentage = 0
		horizontal_scroll_percentage = 0

		if scrollable_height > visible_height:
			max_scroll_top = scrollable_height - visible_height
			vertical_scroll_percentage = (scroll_top / max_scroll_top) * 100 if max_scroll_top > 0 else 0

		if scrollable_width > visible_width:
			max_scroll_left = scrollable_width - visible_width
			horizontal_scroll_percentage = (scroll_left / max_scroll_left) * 100 if max_scroll_left > 0 else 0

		# Calculate pages equivalent (using visible height as page unit)
		pages_above = content_above / visible_height if visible_height > 0 else 0
		pages_below = content_below / visible_height if visible_height > 0 else 0
		total_pages = scrollable_height / visible_height if visible_height > 0 else 1

		return {
			'scroll_top': scroll_top,
			'scroll_left': scroll_left,
			'scrollable_height': scrollable_height,
			'scrollable_width': scrollable_width,
			'visible_height': visible_height,
			'visible_width': visible_width,
			'content_above': content_above,
			'content_below': content_below,
			'content_left': content_left,
			'content_right': content_right,
			'vertical_scroll_percentage': round(vertical_scroll_percentage, 1),
			'horizontal_scroll_percentage': round(horizontal_scroll_percentage, 1),
			'pages_above': round(pages_above, 1),
			'pages_below': round(pages_below, 1),
			'total_pages': round(total_pages, 1),
			'can_scroll_up': content_above > 0,
			'can_scroll_down': content_below > 0,
			'can_scroll_left': content_left > 0,
			'can_scroll_right': content_right > 0,
		}

	def get_scroll_info_text(self) -> str:
		"""Get human-readable scroll information text for this element."""
		# Special case for iframes: check content document for scroll info
		if self.tag_name.lower() == 'iframe':
			# Try to get scroll info from the HTML document inside the iframe
			if self.content_document:
				# Look for HTML element in content document
				html_element = self._find_html_in_content_document()
				if html_element and html_element.scroll_info:
					info = html_element.scroll_info
					# Provide minimal but useful scroll info
					pages_below = info.get('pages_below', 0)
					pages_above = info.get('pages_above', 0)
					v_pct = int(info.get('vertical_scroll_percentage', 0))

					if pages_below > 0 or pages_above > 0:
						return f'scroll: {pages_above:.1f}↑ {pages_below:.1f}↓ {v_pct}%'

			return 'scroll'

		scroll_info = self.scroll_info
		if not scroll_info:
			return ''

		parts = []

		# Vertical scroll info (concise format)
		if scroll_info['scrollable_height'] > scroll_info['visible_height']:
			parts.append(f'{scroll_info["pages_above"]:.1f} pages above, {scroll_info["pages_below"]:.1f} pages below')

		# Horizontal scroll info (concise format)
		if scroll_info['scrollable_width'] > scroll_info['visible_width']:
			parts.append(f'horizontal {scroll_info["horizontal_scroll_percentage"]:.0f}%')

		return ' '.join(parts)

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

		attributes_string = ''.join(
			f'{k}={v}' for k, v in sorted((k, v) for k, v in self.attributes.items() if k in STATIC_ATTRIBUTES)
		)

		# Combine both for final hash
		combined_string = f'{parent_branch_path_string}|{attributes_string}'
		element_hash = hashlib.sha256(combined_string.encode()).hexdigest()

		# Convert to int for __hash__ return type - use first 16 chars and convert from hex to int
		return int(element_hash[:16], 16)

	def parent_branch_hash(self) -> int:
		"""
		Hash the element based on its parent branch path and attributes.
		"""
		parent_branch_path = self._get_parent_branch_path()
		parent_branch_path_string = '/'.join(parent_branch_path)
		element_hash = hashlib.sha256(parent_branch_path_string.encode()).hexdigest()

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

	@observe_debug(ignore_input=True, ignore_output=True, name='llm_representation')
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
			'node_id': self.node_id,
			'backend_node_id': self.backend_node_id,
			'frame_id': self.frame_id,
			'node_type': self.node_type.value,
			'node_value': self.node_value,
			'node_name': self.node_name,
			'attributes': self.attributes,
			'x_path': self.x_path,
			'element_hash': self.element_hash,
			'bounds': self.bounds.to_dict() if self.bounds else None,
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
