# @file purpose: Serializes enhanced DOM trees to string format for LLM consumption


from browser_use.dom.serializer.clickable_elements import ClickableElementDetector
from browser_use.dom.utils import cap_text_length
from browser_use.dom.views import DOMSelectorMap, EnhancedDOMTreeNode, NodeType, SerializedDOMState, SimplifiedNode

DISABLED_ELEMENTS = {'style', 'script', 'head', 'meta', 'link', 'title'}


class DOMTreeSerializer:
	"""Serializes enhanced DOM trees to string format."""

	def __init__(self, root_node: EnhancedDOMTreeNode, previous_cached_state: SerializedDOMState | None = None):
		self.root_node = root_node
		self._interactive_counter = 1
		self._selector_map: DOMSelectorMap = {}
		self._previous_cached_selector_map = previous_cached_state.selector_map if previous_cached_state else None
		# Add timing tracking
		self.timing_info: dict[str, float] = {}
		# Cache for clickable element detection to avoid redundant calls
		self._clickable_cache: dict[int, bool] = {}

	def serialize_accessible_elements(self) -> tuple[SerializedDOMState, dict[str, float]]:
		import time

		start_total = time.time()

		# Reset state
		self._interactive_counter = 1
		self._selector_map = {}
		self._semantic_groups = []
		self._clickable_cache = {}  # Clear cache for new serialization

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

		# # Step 3: Detect and group semantic elements
		# if optimized_tree:
		# 	self._detect_semantic_groups(optimized_tree)

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
		if node.node_id not in self._clickable_cache:
			import time

			start_time = time.time()
			result = ClickableElementDetector.is_interactive(node)
			end_time = time.time()

			if 'clickable_detection_time' not in self.timing_info:
				self.timing_info['clickable_detection_time'] = 0
			self.timing_info['clickable_detection_time'] += end_time - start_time

			self._clickable_cache[node.node_id] = result

		return self._clickable_cache[node.node_id]

	def _create_simplified_tree(self, node: EnhancedDOMTreeNode) -> SimplifiedNode | None:
		"""Step 1: Create a simplified tree with enhanced element detection."""

		if node.node_type == NodeType.DOCUMENT_NODE:
			# for all cldren including shadow roots
			for child in node.children_and_shadow_roots:
				simplified_child = self._create_simplified_tree(child)
				if simplified_child:
					return simplified_child

			return None

		if node.node_type == NodeType.DOCUMENT_FRAGMENT_NODE:
			# Super simple pass-through for shadow DOM elements
			simplified = SimplifiedNode(original_node=node, children=[])
			for child in node.children_and_shadow_roots:
				simplified_child = self._create_simplified_tree(child)
				if simplified_child:
					simplified.children.append(simplified_child)
			return simplified

		elif node.node_type == NodeType.ELEMENT_NODE:
			# Skip non-content elements
			if node.node_name.lower() in DISABLED_ELEMENTS:
				return None

			if node.node_name == 'IFRAME':
				if node.content_document:
					simplified = SimplifiedNode(original_node=node, children=[])
					for child in node.content_document.children:
						simplified_child = self._create_simplified_tree(child)
						if simplified_child:
							simplified.children.append(simplified_child)
					return simplified

			# Use enhanced scoring for inclusion decision
			is_interactive = self._is_interactive_cached(node)

			is_visible = node.snapshot_node and node.is_visible
			is_scrollable = node.is_scrollable

			# Include if interactive (regardless of visibility), or scrollable, or has children to process
			should_include = (is_interactive and is_visible) or is_scrollable or node.children_and_shadow_roots

			if should_include:
				simplified = SimplifiedNode(original_node=node, children=[])
				# simplified._analysis = analysis  # Store analysis for grouping

				# Process children
				for child in node.children_and_shadow_roots:
					simplified_child = self._create_simplified_tree(child)
					if simplified_child:
						simplified.children.append(simplified_child)

				# Return if meaningful or has meaningful children
				if (is_interactive and is_visible) or is_scrollable or simplified.children:
					return simplified

		elif node.node_type == NodeType.TEXT_NODE:
			# Include meaningful text nodes
			is_visible = node.snapshot_node and node.is_visible
			if is_visible and node.node_value and node.node_value.strip() and len(node.node_value.strip()) > 1:
				return SimplifiedNode(original_node=node, children=[])

		return None

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

		# Keep meaningful nodes
		is_interactive_opt = self._is_interactive_cached(node.original_node)
		is_visible = node.original_node.snapshot_node and node.original_node.is_visible

		if (
			(is_interactive_opt and is_visible)  # Only keep interactive nodes that are visible
			or node.original_node.is_scrollable
			or node.original_node.node_type == NodeType.TEXT_NODE
			or node.children
		):
			return node

		return None

	def _collect_interactive_elements(self, node: SimplifiedNode, elements: list[SimplifiedNode]) -> None:
		"""Recursively collect interactive elements that are also visible."""
		is_interactive = self._is_interactive_cached(node.original_node)
		is_visible = node.original_node.snapshot_node and node.original_node.is_visible

		# Only collect elements that are both interactive AND visible
		if is_interactive and is_visible:
			elements.append(node)

		for child in node.children:
			self._collect_interactive_elements(child, elements)

	def _assign_interactive_indices_and_mark_new_nodes(self, node: SimplifiedNode | None) -> None:
		"""Assign interactive indices to clickable elements that are also visible."""
		if not node:
			return

		# Assign index to clickable elements that are also visible
		is_interactive_assign = self._is_interactive_cached(node.original_node)
		is_visible = node.original_node.snapshot_node and node.original_node.is_visible

		# Only add to selector map if element is both interactive AND visible
		if is_interactive_assign and is_visible:
			node.interactive_index = self._interactive_counter
			node.original_node.element_index = self._interactive_counter
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
		"""Serialize the optimized tree to string format."""
		if not node:
			return ''

		formatted_text = []
		depth_str = depth * '\t'
		next_depth = depth

		if node.original_node.node_type == NodeType.ELEMENT_NODE:
			# Skip displaying nodes marked as should_display=False
			if not node.should_display:
				for child in node.children:
					child_text = DOMTreeSerializer.serialize_tree(child, include_attributes, depth)
					if child_text:
						formatted_text.append(child_text)
				return '\n'.join(formatted_text)

			# Add element with interactive_index if clickable, scrollable, or iframe
			if (
				node.interactive_index is not None
				or node.original_node.is_scrollable
				or node.original_node.tag_name.upper() == 'IFRAME'
			):
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
				elif node.original_node.tag_name.upper() == 'IFRAME':
					# Iframe element (not interactive)
					line = f'{depth_str}|IFRAME|<{node.original_node.tag_name}'
				else:
					line = f'{depth_str}<{node.original_node.tag_name}'

				if attributes_html_str:
					line += f' {attributes_html_str}'

				line += ' />'
				formatted_text.append(line)

		elif node.original_node.node_type == NodeType.TEXT_NODE:
			# Include visible text
			is_visible = node.original_node.snapshot_node and node.original_node.is_visible
			if (
				is_visible
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
			return ' '.join(f'{key}={cap_text_length(value, 100)}' for key, value in attributes_to_include.items())

		return ''
