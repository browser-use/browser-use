# @file purpose: Serializes enhanced DOM trees to string format for LLM consumption


import logging

from browser_use.dom.serializer.clickable_elements import ClickableElementDetector
from browser_use.dom.serializer.paint_order import PaintOrderRemover
from browser_use.dom.utils import cap_text_length
from browser_use.dom.views import DOMSelectorMap, EnhancedDOMTreeNode, NodeType, SerializedDOMState, SimplifiedNode
from browser_use.observability import observe_debug
from browser_use.utils import time_execution_sync

logger = logging.getLogger(__name__)


class DOMTreeSerializer:
	"""Serializes enhanced DOM trees to string format."""

	def __init__(self, root_node: EnhancedDOMTreeNode, previous_cached_state: SerializedDOMState | None = None):
		self.root_node = root_node
		self._interactive_counter = 1
		self._selector_map: DOMSelectorMap = {}
		self._previous_cached_selector_map = previous_cached_state.selector_map if previous_cached_state else None
		# Add timing tracking
		self.timing_info: dict[str, float] = {}
		# Cache for clickable element detection to avoid redundant calls (keyed by backend_node_id)
		self._clickable_cache: dict[int, bool] = {}
		# Track frame context for iframe piercing
		self._frame_stack: list[str] = []  # Stack of frame identifiers
		self._iframe_count = 0  # Counter for unnamed iframes

	@time_execution_sync('--serialize_accessible_elements')
	@observe_debug(ignore_input=True, ignore_output=True, name='serialize_accessible_elements')
	def serialize_accessible_elements(self) -> tuple[SerializedDOMState, dict[str, float]]:
		import time

		start_total = time.time()

		# Reset state
		self._interactive_counter = 1
		self._selector_map = {}
		self._semantic_groups = []
		self._clickable_cache = {}  # Clear cache for new serialization
		self._frame_stack = []  # Reset frame stack
		self._iframe_count = 0  # Reset iframe counter

		# Step 1: Create simplified tree (includes clickable element detection)
		start_step1 = time.time()
		simplified_tree = self._create_simplified_tree(self.root_node)
		end_step1 = time.time()
		self.timing_info['create_simplified_tree'] = end_step1 - start_step1

		# Step 2: Optimize tree (remove unnecessary parents)
		start_step2 = time.time()
		optimized_tree = self._optimize_tree(simplified_tree)
		end_step2 = time.time()
		self.timing_info['optimize_tree'] = end_step2 - start_step2

		# Step 3: Remove elements based on paint order
		start_step3 = time.time()
		if optimized_tree:
			PaintOrderRemover(optimized_tree).calculate_paint_order()
		end_step3 = time.time()
		self.timing_info['calculate_paint_order'] = end_step3 - start_step3

		# Step 4: Assign interactive indices to clickable elements
		start_step4 = time.time()
		self._assign_interactive_indices_and_mark_new_nodes(optimized_tree)
		end_step4 = time.time()
		self.timing_info['assign_interactive_indices'] = end_step4 - start_step4

		end_total = time.time()
		self.timing_info['serialize_accessible_elements_total'] = end_total - start_total

		return SerializedDOMState(_root=optimized_tree, selector_map=self._selector_map), self.timing_info

	def _is_interactive_cached(self, node: EnhancedDOMTreeNode) -> bool:
		"""Cached version of clickable element detection to avoid redundant calls."""
		if node.backend_node_id not in self._clickable_cache:
			# Use backend_node_id for more efficient caching (node_id can vary between sessions)
			result = ClickableElementDetector.is_interactive(node)
			self._clickable_cache[node.backend_node_id] = result

		return self._clickable_cache[node.backend_node_id]

	@time_execution_sync('--create_simplified_tree')
	def _create_simplified_tree(self, node: EnhancedDOMTreeNode, is_iframe_content: bool = False) -> SimplifiedNode | None:
		"""Step 1: Create a simplified tree with enhanced element detection and iframe piercing."""

		# Track if we're processing iframe content (relaxed visibility requirements)
		# This parameter gets passed down recursively to maintain iframe context

		if node.node_type == NodeType.DOCUMENT_NODE:
			if node.children_nodes:
				for child in node.children_nodes:
					simplified_child = self._create_simplified_tree(child, is_iframe_content)
					if simplified_child:
						return simplified_child
			return None

		elif node.node_type == NodeType.ELEMENT_NODE:
			if node.node_name == '#document':
				if node.children_nodes:
					for child in node.children_nodes:
						simplified_child = self._create_simplified_tree(child, is_iframe_content)
						if simplified_child:
							return simplified_child
				return None

			# Skip non-content elements
			if node.node_name.lower() in ['style', 'script', 'head', 'meta', 'link', 'title']:
				return None

			# Use enhanced scoring for inclusion decision
			is_interactive = self._is_interactive_cached(node)
			is_visible = node.snapshot_node and node.snapshot_node.is_visible
			is_scrollable = node.is_scrollable
			is_iframe = node.node_name.lower() == 'iframe'

			# Relaxed inclusion criteria for iframe content
			if is_iframe_content:
				# For iframe content, include if interactive OR has children (ignore visibility)
				should_include = is_interactive or is_scrollable or node.children_nodes or is_iframe
			else:
				# Standard criteria for main page content
				should_include = (is_interactive and is_visible) or is_scrollable or node.children_nodes or is_iframe

			if should_include:
				simplified = SimplifiedNode(original_node=node)

				# Mark as iframe content if we're processing iframe content
				if is_iframe_content:
					simplified.is_iframe_content = True

				# Process regular children first
				if node.children_nodes:
					for child in node.children_nodes:
						simplified_child = self._create_simplified_tree(child, is_iframe_content)
						if simplified_child:
							simplified.children.append(simplified_child)

				# Handle iframe content piercing
				if is_iframe and node.content_document:
					iframe_simplified = self._process_iframe_content(node, node.content_document)
					if iframe_simplified:
						simplified.children.append(iframe_simplified)

				# Return if meaningful or has meaningful children
				if is_iframe_content:
					# For iframe content, be more lenient
					if is_interactive or is_scrollable or simplified.children or is_iframe:
						return simplified
				else:
					# Standard criteria for main page
					if (is_interactive and is_visible) or is_scrollable or simplified.children or is_iframe:
						return simplified

		elif node.node_type == NodeType.TEXT_NODE:
			# Include meaningful text nodes
			is_visible = node.snapshot_node and node.snapshot_node.is_visible

			# For iframe content, be more lenient with text nodes
			if is_iframe_content:
				if node.node_value and node.node_value.strip() and len(node.node_value.strip()) > 1:
					simplified = SimplifiedNode(original_node=node)
					simplified.is_iframe_content = True
					return simplified
			else:
				if is_visible and node.node_value and node.node_value.strip() and len(node.node_value.strip()) > 1:
					return SimplifiedNode(original_node=node)

		return None

	def _process_iframe_content(
		self, iframe_node: EnhancedDOMTreeNode, content_document: EnhancedDOMTreeNode
	) -> SimplifiedNode | None:
		"""Process the content document inside an iframe."""
		try:
			# For pierced DOM trees, the content document already contains the iframe's DOM structure
			# We process it with iframe context enabled (relaxed criteria and iframe marking)
			iframe_content = self._create_simplified_tree(content_document, is_iframe_content=True)

			if iframe_content:
				# Mark this as iframe boundary for identification
				iframe_content.is_iframe_boundary = True

			return iframe_content

		except Exception as e:
			# Handle any processing errors gracefully
			logger.debug(f'Warning: Could not process iframe content: {e}')
			return None

	@time_execution_sync('--optimize_tree')
	def _optimize_tree(self, node: SimplifiedNode | None) -> SimplifiedNode | None:
		"""Step 2: Optimize tree structure."""
		if not node:
			return None

		# Process children
		optimized_children = []
		for child in node.children:
			optimized_child = self._optimize_tree(child)
			if optimized_child:
				optimized_children.append(optimized_child)

		node.children = optimized_children

		# Keep meaningful nodes including iframe boundaries
		is_interactive_opt = self._is_interactive_cached(node.original_node)
		is_iframe_boundary = getattr(node, 'is_iframe_boundary', False)

		if (
			is_interactive_opt
			or node.original_node.is_scrollable
			or node.original_node.node_type == NodeType.TEXT_NODE
			or node.children
			or is_iframe_boundary
		):
			return node

		return None

	def _collect_interactive_elements(self, node: SimplifiedNode, elements: list[SimplifiedNode]) -> None:
		"""Recursively collect interactive elements."""
		if self._is_interactive_cached(node.original_node):
			elements.append(node)

		for child in node.children:
			self._collect_interactive_elements(child, elements)

	def _assign_interactive_indices_and_mark_new_nodes(self, node: SimplifiedNode | None) -> None:
		"""Assign interactive indices to clickable elements."""
		if not node:
			return

		# Assign index to clickable elements
		should_assign_index = not node.ignored_by_paint_order and self._is_interactive_cached(node.original_node)

		if should_assign_index:
			node.interactive_index = self._interactive_counter
			self._selector_map[self._interactive_counter] = node.original_node
			self._interactive_counter += 1

			# Check if node is new
			if self._previous_cached_selector_map:
				previous_backend_node_ids = {node.backend_node_id for node in self._previous_cached_selector_map.values()}
				if node.original_node.backend_node_id not in previous_backend_node_ids:
					node.is_new = True

		# Process children
		for child in node.children:
			self._assign_interactive_indices_and_mark_new_nodes(child)

	@staticmethod
	def serialize_tree(node: SimplifiedNode | None, include_attributes: list[str], depth: int = 0) -> str:
		"""Serialize the optimized tree to string format with iframe support."""
		if not node:
			return ''

		formatted_text = []
		depth_str = depth * '\t'
		next_depth = depth

		# Check if this is an iframe boundary
		is_iframe_boundary = getattr(node, 'is_iframe_boundary', False)

		if node.original_node.node_type == NodeType.ELEMENT_NODE:
			# Skip displaying nodes marked as should_display=False
			if not node.should_display:
				for child in node.children:
					child_text = DOMTreeSerializer.serialize_tree(child, include_attributes, depth)
					if child_text:
						formatted_text.append(child_text)
				return '\n'.join(formatted_text)

			# Special handling for iframe boundaries - but only for actual iframe content documents
			if is_iframe_boundary and node.original_node.node_name.lower() in ['html', '#document']:
				# This is an iframe content document - find the parent iframe info
				# Look for iframe attributes in parent context (this is a heuristic)
				formatted_text.append(f'{depth_str}┌── IFRAME START (content document) ──')
				next_depth += 1

			# Add element with interactive_index if clickable or scrollable
			elif node.interactive_index is not None or node.original_node.is_scrollable:
				next_depth += 1

				# Build attributes string
				attributes_html_str = DOMTreeSerializer._build_attributes_string(node.original_node, include_attributes, '')

				# Build the line
				if node.original_node.is_scrollable and node.interactive_index is None:
					# Scrollable but not clickable
					line = f'{depth_str}|SCROLL|<{node.original_node.tag_name}'
				elif node.interactive_index is not None:
					# Clickable (and possibly scrollable)
					new_prefix = '*' if node.is_new else ''
					scroll_prefix = '|SCROLL+' if node.original_node.is_scrollable else '['
					line = f'{depth_str}{new_prefix}{scroll_prefix}{node.interactive_index}]<{node.original_node.tag_name}'
				else:
					line = f'{depth_str}<{node.original_node.tag_name}'

				if attributes_html_str:
					line += f' {attributes_html_str}'

				line += ' />'
				formatted_text.append(line)

		elif node.original_node.node_type == NodeType.TEXT_NODE:
			# Include visible text or iframe content text
			is_visible = node.original_node.snapshot_node and node.original_node.snapshot_node.is_visible
			is_iframe_text = getattr(node, 'is_iframe_content', False)

			# Include text if visible OR if it's iframe content (which lacks visibility data)
			if (
				(is_visible or is_iframe_text)
				and node.original_node.node_value
				and node.original_node.node_value.strip()
				and len(node.original_node.node_value.strip()) > 1
			):
				clean_text = node.original_node.node_value.strip()
				formatted_text.append(f'{depth_str}{clean_text}')

		# Process children
		for child in node.children:
			child_text = DOMTreeSerializer.serialize_tree(child, include_attributes, next_depth)
			if child_text:
				formatted_text.append(child_text)

		# Close iframe boundary
		if is_iframe_boundary and node.original_node.node_name.lower() in ['html', '#document'] and formatted_text:
			formatted_text.append(f'{depth_str}└── IFRAME END ──')

		return '\n'.join(formatted_text)

	@staticmethod
	def _build_attributes_string(node: EnhancedDOMTreeNode, include_attributes: list[str], text: str) -> str:
		"""Build the attributes string for an element."""
		if not node.attributes:
			return ''

		attributes_to_include = {
			key: str(value).strip()
			for key, value in node.attributes.items()
			if key in include_attributes and str(value).strip() != ''
		}

		# Remove duplicate values
		ordered_keys = [key for key in include_attributes if key in attributes_to_include]

		if len(ordered_keys) > 1:
			keys_to_remove = set()
			seen_values = {}

			for key in ordered_keys:
				value = attributes_to_include[key]
				if len(value) > 5:
					if value in seen_values:
						keys_to_remove.add(key)
					else:
						seen_values[value] = key

			for key in keys_to_remove:
				del attributes_to_include[key]

		# Remove attributes that duplicate accessibility data
		role = node.ax_node.role if node.ax_node else None
		if role and node.node_name == role:
			attributes_to_include.pop('role', None)

		attrs_to_remove_if_text_matches = ['aria-label', 'placeholder', 'title']
		for attr in attrs_to_remove_if_text_matches:
			if attributes_to_include.get(attr) and attributes_to_include.get(attr, '').strip().lower() == text.strip().lower():
				del attributes_to_include[attr]

		if attributes_to_include:
			return ' '.join(f'{key}={cap_text_length(value, 15)}' for key, value in attributes_to_include.items())

		return ''
