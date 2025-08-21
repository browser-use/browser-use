# @file purpose: Serializes enhanced DOM trees to string format for LLM consumption


from browser_use.dom.serializer.clickable_elements import ClickableElementDetector
from browser_use.dom.utils import cap_text_length
from browser_use.dom.views import (
	DOMRect,
	DOMSelectorMap,
	EnhancedDOMTreeNode,
	NodeType,
	PropagatingBounds,
	SerializedDOMState,
	SimplifiedNode,
)

DISABLED_ELEMENTS = {'style', 'script', 'head', 'meta', 'link', 'title'}


class DOMTreeSerializer:
	"""Serializes enhanced DOM trees to string format."""

	# Configuration - elements that propagate bounds to their children
	PROPAGATING_ELEMENTS = [
		{'tag': 'a', 'role': None},  # Any <a> tag
		{'tag': 'button', 'role': None},  # Any <button> tag
		{'tag': 'div', 'role': 'button'},  # <div role="button">
		{'tag': 'div', 'role': 'combobox'},  # <div role="combobox"> - dropdowns/selects
		{'tag': 'span', 'role': 'button'},  # <span role="button">
		{'tag': 'span', 'role': 'combobox'},  # <span role="combobox">
		{'tag': 'input', 'role': 'combobox'},  # <input role="combobox"> - autocomplete inputs
		{'tag': 'input', 'role': 'combobox'},  # <input type="text"> - text inputs with suggestions
		# {'tag': 'div', 'role': 'link'},     # <div role="link">
		# {'tag': 'span', 'role': 'link'},    # <span role="link">
	]
	DEFAULT_CONTAINMENT_THRESHOLD = 0.99  # 99% containment by default

	def __init__(
		self,
		root_node: EnhancedDOMTreeNode,
		previous_cached_state: SerializedDOMState | None = None,
		enable_bbox_filtering: bool = True,
		containment_threshold: float | None = None,
	):
		self.root_node = root_node
		self._interactive_counter = 1
		self._selector_map: DOMSelectorMap = {}
		self._previous_cached_selector_map = previous_cached_state.selector_map if previous_cached_state else None
		# Add timing tracking
		self.timing_info: dict[str, float] = {}
		# Cache for clickable element detection to avoid redundant calls
		self._clickable_cache: dict[int, bool] = {}
		# Bounding box filtering configuration
		self.enable_bbox_filtering = enable_bbox_filtering
		self.containment_threshold = containment_threshold or self.DEFAULT_CONTAINMENT_THRESHOLD

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
		#   self._detect_semantic_groups(optimized_tree)

		# Step 3: Apply bounding box filtering (NEW)
		if self.enable_bbox_filtering and optimized_tree:
			start_step3 = time.time()
			filtered_tree = self._apply_bounding_box_filtering(optimized_tree)
			end_step3 = time.time()
			self.timing_info['bbox_filtering'] = end_step3 - start_step3
		else:
			filtered_tree = optimized_tree

		# Step 4: Assign interactive indices to clickable elements
		start_step4 = time.time()
		self._assign_interactive_indices_and_mark_new_nodes(filtered_tree)
		end_step4 = time.time()
		self.timing_info['assign_interactive_indices'] = end_step4 - start_step4

		end_total = time.time()
		self.timing_info['serialize_accessible_elements_total'] = end_total - start_total

		return SerializedDOMState(_root=filtered_tree, selector_map=self._selector_map), self.timing_info

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
			is_scrollable = node.is_actually_scrollable

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
			or node.original_node.is_actually_scrollable
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

		# Skip assigning index to excluded nodes
		if not (hasattr(node, 'excluded_by_parent') and node.excluded_by_parent):
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

	def _apply_bounding_box_filtering(self, node: SimplifiedNode | None) -> SimplifiedNode | None:
		"""Filter children contained within propagating parent bounds."""
		if not node:
			return None

		# Start with no active bounds
		self._filter_tree_recursive(node, active_bounds=None, depth=0)

		# Log statistics
		excluded_count = self._count_excluded_nodes(node)
		if excluded_count > 0:
			import logging

			logging.debug(f'BBox filtering excluded {excluded_count} nodes')

		return node

	def _filter_tree_recursive(self, node: SimplifiedNode, active_bounds: PropagatingBounds | None = None, depth: int = 0):
		"""
		Recursively filter tree with bounding box propagation.
		Bounds propagate to ALL descendants until overridden.
		"""

		# Check if this node should be excluded by active bounds
		if active_bounds and self._should_exclude_child(node, active_bounds):
			node.excluded_by_parent = True
			# Important: Still check if this node starts NEW propagation

		# Check if this node starts new propagation (even if excluded!)
		new_bounds = None
		tag = node.original_node.tag_name.lower()
		role = node.original_node.attributes.get('role') if node.original_node.attributes else None
		attributes = {
			'tag': tag,
			'role': role,
		}
		# Check if this element matches any propagating element pattern
		if self._is_propagating_element(attributes):
			# This node propagates bounds to ALL its descendants
			if node.original_node.snapshot_node and node.original_node.snapshot_node.bounds:
				new_bounds = PropagatingBounds(
					tag=tag,
					bounds=node.original_node.snapshot_node.bounds,
					node_id=node.original_node.node_id,
					depth=depth,
				)

		# Propagate to ALL children
		# Use new_bounds if this node starts propagation, otherwise continue with active_bounds
		propagate_bounds = new_bounds if new_bounds else active_bounds

		for child in node.children:
			self._filter_tree_recursive(child, propagate_bounds, depth + 1)

	def _should_exclude_child(self, node: SimplifiedNode, active_bounds: PropagatingBounds) -> bool:
		"""
		Determine if child should be excluded based on propagating bounds.
		"""

		# Never exclude text nodes - we always want to preserve text content
		if node.original_node.node_type == NodeType.TEXT_NODE:
			return False

		# Get child bounds
		if not node.original_node.snapshot_node or not node.original_node.snapshot_node.bounds:
			return False  # No bounds = can't determine containment

		child_bounds = node.original_node.snapshot_node.bounds

		# Check containment with configured threshold
		if not self._is_contained(child_bounds, active_bounds.bounds, self.containment_threshold):
			return False  # Not sufficiently contained

		# EXCEPTION RULES - Keep these even if contained:

		child_tag = node.original_node.tag_name.lower()
		child_role = node.original_node.attributes.get('role') if node.original_node.attributes else None
		child_attributes = {
			'tag': child_tag,
			'role': child_role,
		}

		# 1. Never exclude form elements (they need individual interaction)
		if child_tag in ['input', 'select', 'textarea', 'label']:
			return False

		# 2. Keep if child is also a propagating element
		# (might have stopPropagation, e.g., button in button)
		if self._is_propagating_element(child_attributes):
			return False

		# 3. Keep if has explicit onclick handler
		if node.original_node.attributes and 'onclick' in node.original_node.attributes:
			return False

		# 4. Keep if has aria-label suggesting it's independently interactive
		if node.original_node.attributes:
			aria_label = node.original_node.attributes.get('aria-label')
			if aria_label and aria_label.strip():
				# Has meaningful aria-label, likely interactive
				return False

		# 5. Keep if has role suggesting interactivity
		if node.original_node.attributes:
			role = node.original_node.attributes.get('role')
			if role in ['button', 'link', 'checkbox', 'radio', 'tab', 'menuitem']:
				return False

		# Default: exclude this child
		return True

	def _is_contained(self, child: DOMRect, parent: DOMRect, threshold: float) -> bool:
		"""
		Check if child is contained within parent bounds.

		Args:
			threshold: Percentage (0.0-1.0) of child that must be within parent
		"""
		# Calculate intersection
		x_overlap = max(0, min(child.x + child.width, parent.x + parent.width) - max(child.x, parent.x))
		y_overlap = max(0, min(child.y + child.height, parent.y + parent.height) - max(child.y, parent.y))

		intersection_area = x_overlap * y_overlap
		child_area = child.width * child.height

		if child_area == 0:
			return False  # Zero-area element

		containment_ratio = intersection_area / child_area
		return containment_ratio >= threshold

	def _count_excluded_nodes(self, node: SimplifiedNode, count: int = 0) -> int:
		"""Count how many nodes were excluded (for debugging)."""
		if hasattr(node, 'excluded_by_parent') and node.excluded_by_parent:
			count += 1
		for child in node.children:
			count = self._count_excluded_nodes(child, count)
		return count

	def _is_propagating_element(self, attributes: dict[str, str | None]) -> bool:
		"""
		Check if an element should propagate bounds based on attributes.
		If the element satisfies one of the patterns, it propagates bounds to all its children.
		"""
		keys_to_check = ['tag', 'role']
		for pattern in self.PROPAGATING_ELEMENTS:
			# Check if the element satisfies the pattern
			check = [pattern.get(key) is None or pattern.get(key) == attributes.get(key) for key in keys_to_check]
			if all(check):
				return True

		return False

	@staticmethod
	def serialize_tree(node: SimplifiedNode | None, include_attributes: list[str], depth: int = 0) -> str:
		"""Serialize the optimized tree to string format."""
		if not node:
			return ''

		# Skip rendering excluded nodes, but process their children
		if hasattr(node, 'excluded_by_parent') and node.excluded_by_parent:
			formatted_text = []
			for child in node.children:
				child_text = DOMTreeSerializer.serialize_tree(child, include_attributes, depth)
				if child_text:
					formatted_text.append(child_text)
			return '\n'.join(formatted_text)

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
			is_any_scrollable = node.original_node.is_actually_scrollable or node.original_node.is_scrollable
			should_show_scroll = node.original_node.should_show_scroll_info
			if node.interactive_index is not None or is_any_scrollable or node.original_node.tag_name.upper() == 'IFRAME':
				next_depth += 1

				# Build attributes string
				attributes_html_str = DOMTreeSerializer._build_attributes_string(node.original_node, include_attributes, '')

				# Build the line
				if should_show_scroll and node.interactive_index is None:
					# Scrollable container but not clickable
					line = f'{depth_str}|SCROLL|<{node.original_node.tag_name}'
				elif node.interactive_index is not None:
					# Clickable (and possibly scrollable)
					new_prefix = '*' if node.is_new else ''
					scroll_prefix = '|SCROLL+' if should_show_scroll else '['
					line = f'{depth_str}{new_prefix}{scroll_prefix}{node.interactive_index}]<{node.original_node.tag_name}'
				elif node.original_node.tag_name.upper() == 'IFRAME':
					# Iframe element (not interactive)
					line = f'{depth_str}|IFRAME|<{node.original_node.tag_name}'
				else:
					line = f'{depth_str}<{node.original_node.tag_name}'

				if attributes_html_str:
					line += f' {attributes_html_str}'

				line += ' />'

				# Add scroll information only when we should show it
				if should_show_scroll:
					scroll_info_text = node.original_node.get_scroll_info_text()
					if scroll_info_text:
						line += f' ({scroll_info_text})'

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
		attributes_to_include = {}

		# Include HTML attributes
		if node.attributes:
			attributes_to_include.update(
				{
					key: str(value).strip()
					for key, value in node.attributes.items()
					if key in include_attributes and str(value).strip() != ''
				}
			)

		# Include accessibility properties
		if node.ax_node and node.ax_node.properties:
			for prop in node.ax_node.properties:
				try:
					if prop.name in include_attributes and prop.value is not None:
						# Convert boolean to lowercase string, keep others as-is
						if isinstance(prop.value, bool):
							attributes_to_include[prop.name] = str(prop.value).lower()
						else:
							prop_value_str = str(prop.value).strip()
							if prop_value_str:
								attributes_to_include[prop.name] = prop_value_str
				except (AttributeError, ValueError):
					continue

		if not attributes_to_include:
			return ''

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
