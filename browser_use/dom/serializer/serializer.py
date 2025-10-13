# @file purpose: Serializes enhanced DOM trees to string format for LLM consumption

from typing import Any

from browser_use.dom.serializer.clickable_elements import ClickableElementDetector
from browser_use.dom.serializer.paint_order import PaintOrderRemover
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
		paint_order_filtering: bool = True,
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
		# Paint order filtering configuration
		self.paint_order_filtering = paint_order_filtering

	def _safe_parse_number(self, value_str: str, default: float) -> float:
		"""Parse string to float, handling negatives and decimals."""
		try:
			return float(value_str)
		except (ValueError, TypeError):
			return default

	def _safe_parse_optional_number(self, value_str: str | None) -> float | None:
		"""Parse string to float, returning None for invalid values."""
		if not value_str:
			return None
		try:
			return float(value_str)
		except (ValueError, TypeError):
			return None

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

		# Step 2: Remove elements based on paint order
		start_step3 = time.time()
		if self.paint_order_filtering and simplified_tree:
			PaintOrderRemover(simplified_tree).calculate_paint_order()
		end_step3 = time.time()
		self.timing_info['calculate_paint_order'] = end_step3 - start_step3

		# Step 3: Optimize tree (remove unnecessary parents)
		start_step2 = time.time()
		optimized_tree = self._optimize_tree(simplified_tree)
		end_step2 = time.time()
		self.timing_info['optimize_tree'] = end_step2 - start_step2

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

	def _add_compound_components(self, simplified: SimplifiedNode, node: EnhancedDOMTreeNode) -> None:
		"""Enhance compound controls with information from their child components."""
		# Only process elements that might have compound components
		if node.tag_name not in ['input', 'select', 'details', 'audio', 'video']:
			return

		# For input elements, check for compound input types
		if node.tag_name == 'input':
			if not node.attributes or node.attributes.get('type') not in [
				'date',
				'time',
				'datetime-local',
				'month',
				'week',
				'range',
				'number',
				'color',
				'file',
			]:
				return
		# For other elements, check if they have AX child indicators
		elif not node.ax_node or not node.ax_node.child_ids:
			return

		# Add compound component information based on element type
		element_type = node.tag_name
		input_type = node.attributes.get('type', '') if node.attributes else ''

		if element_type == 'input':
			if input_type == 'date':
				node._compound_children.extend(
					[
						{'role': 'spinbutton', 'name': 'Day', 'valuemin': 1, 'valuemax': 31, 'valuenow': None},
						{'role': 'spinbutton', 'name': 'Month', 'valuemin': 1, 'valuemax': 12, 'valuenow': None},
						{'role': 'spinbutton', 'name': 'Year', 'valuemin': 1, 'valuemax': 275760, 'valuenow': None},
					]
				)
				simplified.is_compound_component = True
			elif input_type == 'time':
				node._compound_children.extend(
					[
						{'role': 'spinbutton', 'name': 'Hour', 'valuemin': 0, 'valuemax': 23, 'valuenow': None},
						{'role': 'spinbutton', 'name': 'Minute', 'valuemin': 0, 'valuemax': 59, 'valuenow': None},
					]
				)
				simplified.is_compound_component = True
			elif input_type == 'datetime-local':
				node._compound_children.extend(
					[
						{'role': 'spinbutton', 'name': 'Day', 'valuemin': 1, 'valuemax': 31, 'valuenow': None},
						{'role': 'spinbutton', 'name': 'Month', 'valuemin': 1, 'valuemax': 12, 'valuenow': None},
						{'role': 'spinbutton', 'name': 'Year', 'valuemin': 1, 'valuemax': 275760, 'valuenow': None},
						{'role': 'spinbutton', 'name': 'Hour', 'valuemin': 0, 'valuemax': 23, 'valuenow': None},
						{'role': 'spinbutton', 'name': 'Minute', 'valuemin': 0, 'valuemax': 59, 'valuenow': None},
					]
				)
				simplified.is_compound_component = True
			elif input_type == 'month':
				node._compound_children.extend(
					[
						{'role': 'spinbutton', 'name': 'Month', 'valuemin': 1, 'valuemax': 12, 'valuenow': None},
						{'role': 'spinbutton', 'name': 'Year', 'valuemin': 1, 'valuemax': 275760, 'valuenow': None},
					]
				)
				simplified.is_compound_component = True
			elif input_type == 'week':
				node._compound_children.extend(
					[
						{'role': 'spinbutton', 'name': 'Week', 'valuemin': 1, 'valuemax': 53, 'valuenow': None},
						{'role': 'spinbutton', 'name': 'Year', 'valuemin': 1, 'valuemax': 275760, 'valuenow': None},
					]
				)
				simplified.is_compound_component = True
			elif input_type == 'range':
				# Range slider with value indicator
				min_val = node.attributes.get('min', '0') if node.attributes else '0'
				max_val = node.attributes.get('max', '100') if node.attributes else '100'

				node._compound_children.append(
					{
						'role': 'slider',
						'name': 'Value',
						'valuemin': self._safe_parse_number(min_val, 0.0),
						'valuemax': self._safe_parse_number(max_val, 100.0),
						'valuenow': None,
					}
				)
				simplified.is_compound_component = True
			elif input_type == 'number':
				# Number input with increment/decrement buttons
				min_val = node.attributes.get('min') if node.attributes else None
				max_val = node.attributes.get('max') if node.attributes else None

				node._compound_children.extend(
					[
						{'role': 'button', 'name': 'Increment', 'valuemin': None, 'valuemax': None, 'valuenow': None},
						{'role': 'button', 'name': 'Decrement', 'valuemin': None, 'valuemax': None, 'valuenow': None},
						{
							'role': 'textbox',
							'name': 'Value',
							'valuemin': self._safe_parse_optional_number(min_val),
							'valuemax': self._safe_parse_optional_number(max_val),
							'valuenow': None,
						},
					]
				)
				simplified.is_compound_component = True
			elif input_type == 'color':
				# Color picker with components
				node._compound_children.extend(
					[
						{'role': 'textbox', 'name': 'Hex Value', 'valuemin': None, 'valuemax': None, 'valuenow': None},
						{'role': 'button', 'name': 'Color Picker', 'valuemin': None, 'valuemax': None, 'valuenow': None},
					]
				)
				simplified.is_compound_component = True
			elif input_type == 'file':
				# File input with browse button
				multiple = 'multiple' in node.attributes if node.attributes else False
				node._compound_children.extend(
					[
						{'role': 'button', 'name': 'Browse Files', 'valuemin': None, 'valuemax': None, 'valuenow': None},
						{
							'role': 'textbox',
							'name': f'{"Files" if multiple else "File"} Selected',
							'valuemin': None,
							'valuemax': None,
							'valuenow': None,
						},
					]
				)
				simplified.is_compound_component = True

		elif element_type == 'select':
			# Select dropdown with option list and detailed option information
			base_components = [
				{'role': 'button', 'name': 'Dropdown Toggle', 'valuemin': None, 'valuemax': None, 'valuenow': None}
			]

			# Extract option information from child nodes
			options_info = self._extract_select_options(node)
			if options_info:
				options_component = {
					'role': 'listbox',
					'name': 'Options',
					'valuemin': None,
					'valuemax': None,
					'valuenow': None,
					'options_count': options_info['count'],
					'first_options': options_info['first_options'],
				}
				if options_info['format_hint']:
					options_component['format_hint'] = options_info['format_hint']
				base_components.append(options_component)
			else:
				base_components.append(
					{'role': 'listbox', 'name': 'Options', 'valuemin': None, 'valuemax': None, 'valuenow': None}
				)

			node._compound_children.extend(base_components)
			simplified.is_compound_component = True

		elif element_type == 'details':
			# Details/summary disclosure widget
			node._compound_children.extend(
				[
					{'role': 'button', 'name': 'Toggle Disclosure', 'valuemin': None, 'valuemax': None, 'valuenow': None},
					{'role': 'region', 'name': 'Content Area', 'valuemin': None, 'valuemax': None, 'valuenow': None},
				]
			)
			simplified.is_compound_component = True

		elif element_type == 'audio':
			# Audio player controls
			node._compound_children.extend(
				[
					{'role': 'button', 'name': 'Play/Pause', 'valuemin': None, 'valuemax': None, 'valuenow': None},
					{'role': 'slider', 'name': 'Progress', 'valuemin': 0, 'valuemax': 100, 'valuenow': None},
					{'role': 'button', 'name': 'Mute', 'valuemin': None, 'valuemax': None, 'valuenow': None},
					{'role': 'slider', 'name': 'Volume', 'valuemin': 0, 'valuemax': 100, 'valuenow': None},
				]
			)
			simplified.is_compound_component = True

		elif element_type == 'video':
			# Video player controls
			node._compound_children.extend(
				[
					{'role': 'button', 'name': 'Play/Pause', 'valuemin': None, 'valuemax': None, 'valuenow': None},
					{'role': 'slider', 'name': 'Progress', 'valuemin': 0, 'valuemax': 100, 'valuenow': None},
					{'role': 'button', 'name': 'Mute', 'valuemin': None, 'valuemax': None, 'valuenow': None},
					{'role': 'slider', 'name': 'Volume', 'valuemin': 0, 'valuemax': 100, 'valuenow': None},
					{'role': 'button', 'name': 'Fullscreen', 'valuemin': None, 'valuemax': None, 'valuenow': None},
				]
			)
			simplified.is_compound_component = True

	def _extract_select_options(self, select_node: EnhancedDOMTreeNode) -> dict[str, Any] | None:
		"""Extract option information from a select element."""
		if not select_node.children:
			return None

		options = []
		option_values = []

		def extract_options_recursive(node: EnhancedDOMTreeNode) -> None:
			"""Recursively extract option elements, including from optgroups."""
			if node.tag_name.lower() == 'option':
				# Extract option text and value
				option_text = ''
				option_value = ''

				# Get value attribute if present
				if node.attributes and 'value' in node.attributes:
					option_value = str(node.attributes['value']).strip()

				# Get text content from direct child text nodes only to avoid duplication
				def get_direct_text_content(n: EnhancedDOMTreeNode) -> str:
					text = ''
					for child in n.children:
						if child.node_type == NodeType.TEXT_NODE and child.node_value:
							text += child.node_value.strip() + ' '
					return text.strip()

				option_text = get_direct_text_content(node)

				# Use text as value if no explicit value
				if not option_value and option_text:
					option_value = option_text

				if option_text or option_value:
					options.append({'text': option_text, 'value': option_value})
					option_values.append(option_value)

			elif node.tag_name.lower() == 'optgroup':
				# Process optgroup children
				for child in node.children:
					extract_options_recursive(child)
			else:
				# Process other children that might contain options
				for child in node.children:
					extract_options_recursive(child)

		# Extract all options from select children
		for child in select_node.children:
			extract_options_recursive(child)

		if not options:
			return None

		# Prepare first 4 options for display
		first_options = []
		for option in options[:4]:
			if option['text'] and option['value'] and option['text'] != option['value']:
				# Limit individual option text to avoid overly long attributes
				text = option['text'][:20] + ('...' if len(option['text']) > 20 else '')
				value = option['value'][:10] + ('...' if len(option['value']) > 10 else '')
				first_options.append(f'{text} ({value})')
			elif option['text']:
				text = option['text'][:25] + ('...' if len(option['text']) > 25 else '')
				first_options.append(text)
			elif option['value']:
				value = option['value'][:25] + ('...' if len(option['value']) > 25 else '')
				first_options.append(value)

		# Try to infer format hint from option values
		format_hint = None
		if len(option_values) >= 2:
			# Check for common patterns
			if all(val.isdigit() for val in option_values[:5] if val):
				format_hint = 'numeric'
			elif all(len(val) == 2 and val.isupper() for val in option_values[:5] if val):
				format_hint = 'country/state codes'
			elif all('/' in val or '-' in val for val in option_values[:5] if val):
				format_hint = 'date/path format'
			elif any('@' in val for val in option_values[:5] if val):
				format_hint = 'email addresses'

		return {'count': len(options), 'first_options': first_options, 'format_hint': format_hint}

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

	def _create_simplified_tree(self, node: EnhancedDOMTreeNode, depth: int = 0) -> SimplifiedNode | None:
		"""Step 1: Create a simplified tree with enhanced element detection."""

		if node.node_type == NodeType.DOCUMENT_NODE:
			# for all cldren including shadow roots
			for child in node.children_and_shadow_roots:
				simplified_child = self._create_simplified_tree(child, depth + 1)
				if simplified_child:
					return simplified_child

			return None

		if node.node_type == NodeType.DOCUMENT_FRAGMENT_NODE:
			# ENHANCED shadow DOM processing - always include shadow content
			simplified = SimplifiedNode(original_node=node, children=[])
			for child in node.children_and_shadow_roots:
				simplified_child = self._create_simplified_tree(child, depth + 1)
				if simplified_child:
					simplified.children.append(simplified_child)

			# Always return shadow DOM fragments, even if children seem empty
			# Shadow DOM often contains the actual interactive content in SPAs
			return simplified if simplified.children else SimplifiedNode(original_node=node, children=[])

		elif node.node_type == NodeType.ELEMENT_NODE:
			# Skip non-content elements
			if node.node_name.lower() in DISABLED_ELEMENTS:
				return None

			if node.node_name == 'IFRAME' or node.node_name == 'FRAME':
				if node.content_document:
					simplified = SimplifiedNode(original_node=node, children=[])
					for child in node.content_document.children_nodes or []:
						simplified_child = self._create_simplified_tree(child, depth + 1)
						if simplified_child is not None:
							simplified.children.append(simplified_child)
					return simplified

			is_visible = node.is_visible
			is_scrollable = node.is_actually_scrollable
			has_shadow_content = bool(node.children_and_shadow_roots)

			# ENHANCED SHADOW DOM DETECTION: Include shadow hosts even if not visible
			is_shadow_host = any(child.node_type == NodeType.DOCUMENT_FRAGMENT_NODE for child in node.children_and_shadow_roots)

			# Override visibility for elements with validation attributes
			if not is_visible and node.attributes:
				has_validation_attrs = any(attr.startswith(('aria-', 'pseudo')) for attr in node.attributes.keys())
				if has_validation_attrs:
					is_visible = True  # Force visibility for validation elements

			# Include if visible, scrollable, has children, or is shadow host
			if is_visible or is_scrollable or has_shadow_content or is_shadow_host:
				simplified = SimplifiedNode(original_node=node, children=[], is_shadow_host=is_shadow_host)

				# Process ALL children including shadow roots with enhanced logging
				for child in node.children_and_shadow_roots:
					simplified_child = self._create_simplified_tree(child, depth + 1)
					if simplified_child:
						simplified.children.append(simplified_child)

				# COMPOUND CONTROL PROCESSING: Add virtual components for compound controls
				self._add_compound_components(simplified, node)

				# SHADOW DOM SPECIAL CASE: Always include shadow hosts even if not visible
				# Many SPA frameworks (React, Vue) render content in shadow DOM
				if is_shadow_host and simplified.children:
					return simplified

				# Return if meaningful or has meaningful children
				if is_visible or is_scrollable or simplified.children:
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
		is_visible = node.original_node.snapshot_node and node.original_node.is_visible

		if (
			is_visible  # Keep all visible nodes
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

		# Skip assigning index to excluded nodes, or ignored by paint order
		if not node.excluded_by_parent and not node.ignored_by_paint_order:
			# Regular interactive element assignment (including enhanced compound controls)
			is_interactive_assign = self._is_interactive_cached(node.original_node)
			is_visible = node.original_node.snapshot_node and node.original_node.is_visible

			# Only add to selector map if element is both interactive AND visible
			if is_interactive_assign and is_visible:
				node.interactive_index = self._interactive_counter
				node.original_node.element_index = self._interactive_counter
				self._selector_map[self._interactive_counter] = node.original_node
				self._interactive_counter += 1

				# Mark compound components as new for visibility
				if node.is_compound_component:
					node.is_new = True
				elif self._previous_cached_selector_map:
					# Check if node is new for regular elements
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
			if role in ['button', 'link', 'checkbox', 'radio', 'tab', 'menuitem', 'option']:
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
			if (
				node.interactive_index is not None
				or is_any_scrollable
				or node.original_node.tag_name.upper() == 'IFRAME'
				or node.original_node.tag_name.upper() == 'FRAME'
			):
				next_depth += 1

				# Build attributes string with compound component info
				text_content = ''
				attributes_html_str = DOMTreeSerializer._build_attributes_string(
					node.original_node, include_attributes, text_content
				)

				# Add compound component information to attributes if present
				if node.original_node._compound_children:
					compound_info = []
					for child_info in node.original_node._compound_children:
						parts = []
						if child_info['name']:
							parts.append(f'name={child_info["name"]}')
						if child_info['role']:
							parts.append(f'role={child_info["role"]}')
						if child_info['valuemin'] is not None:
							parts.append(f'min={child_info["valuemin"]}')
						if child_info['valuemax'] is not None:
							parts.append(f'max={child_info["valuemax"]}')
						if child_info['valuenow'] is not None:
							parts.append(f'current={child_info["valuenow"]}')

						# Add select-specific information
						if 'options_count' in child_info and child_info['options_count'] is not None:
							parts.append(f'count={child_info["options_count"]}')
						if 'first_options' in child_info and child_info['first_options']:
							options_str = '|'.join(child_info['first_options'][:4])  # Limit to 4 options
							parts.append(f'options={options_str}')
						if 'format_hint' in child_info and child_info['format_hint']:
							parts.append(f'format={child_info["format_hint"]}')

						if parts:
							compound_info.append(f'({",".join(parts)})')

					if compound_info:
						compound_attr = f'compound_components={",".join(compound_info)}'
						if attributes_html_str:
							attributes_html_str += f' {compound_attr}'
						else:
							attributes_html_str = compound_attr

				# Build the line with shadow host indicator
				shadow_prefix = ''
				if node.is_shadow_host:
					# Check if any shadow children are closed
					has_closed_shadow = any(
						child.original_node.node_type == NodeType.DOCUMENT_FRAGMENT_NODE
						and child.original_node.shadow_root_type
						and child.original_node.shadow_root_type.lower() == 'closed'
						for child in node.children
					)
					shadow_prefix = '|SHADOW(closed)|' if has_closed_shadow else '|SHADOW(open)|'

				if should_show_scroll and node.interactive_index is None:
					# Scrollable container but not clickable
					line = f'{depth_str}{shadow_prefix}|SCROLL|<{node.original_node.tag_name}'
				elif node.interactive_index is not None:
					# Clickable (and possibly scrollable)
					new_prefix = '*' if node.is_new else ''
					scroll_prefix = '|SCROLL[' if should_show_scroll else '['
					line = f'{depth_str}{shadow_prefix}{new_prefix}{scroll_prefix}{node.interactive_index}]<{node.original_node.tag_name}'
				elif node.original_node.tag_name.upper() == 'IFRAME':
					# Iframe element (not interactive)
					line = f'{depth_str}{shadow_prefix}|IFRAME|<{node.original_node.tag_name}'
				elif node.original_node.tag_name.upper() == 'FRAME':
					# Frame element (not interactive)
					line = f'{depth_str}{shadow_prefix}|FRAME|<{node.original_node.tag_name}'
				else:
					line = f'{depth_str}{shadow_prefix}<{node.original_node.tag_name}'

				if attributes_html_str:
					line += f' {attributes_html_str}'

				line += ' />'

				# Add scroll information only when we should show it
				if should_show_scroll:
					scroll_info_text = node.original_node.get_scroll_info_text()
					if scroll_info_text:
						line += f' ({scroll_info_text})'

				formatted_text.append(line)

		elif node.original_node.node_type == NodeType.DOCUMENT_FRAGMENT_NODE:
			# Shadow DOM representation - show clearly to LLM
			if node.original_node.shadow_root_type and node.original_node.shadow_root_type.lower() == 'closed':
				formatted_text.append(f'{depth_str}Closed Shadow')
			else:
				formatted_text.append(f'{depth_str}Open Shadow')

			next_depth += 1

			# Process shadow DOM children
			for child in node.children:
				child_text = DOMTreeSerializer.serialize_tree(child, include_attributes, next_depth)
				if child_text:
					formatted_text.append(child_text)

			# Close shadow DOM indicator
			if node.children:  # Only show close if we had content
				formatted_text.append(f'{depth_str}Shadow End')

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

		# Process children (for non-shadow elements)
		if node.original_node.node_type != NodeType.DOCUMENT_FRAGMENT_NODE:
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

		# Remove type attribute if it matches the tag name (e.g. <button type="button">)
		if 'type' in attributes_to_include and attributes_to_include['type'].lower() == node.node_name.lower():
			del attributes_to_include['type']

		# Remove invalid attribute if it's false (only show when true)
		if 'invalid' in attributes_to_include and attributes_to_include['invalid'].lower() == 'false':
			del attributes_to_include['invalid']

		# Remove aria-expanded if we have expanded (prefer AX tree over HTML attribute)
		if 'expanded' in attributes_to_include and 'aria-expanded' in attributes_to_include:
			del attributes_to_include['aria-expanded']

		attrs_to_remove_if_text_matches = ['aria-label', 'placeholder', 'title']
		for attr in attrs_to_remove_if_text_matches:
			if attributes_to_include.get(attr) and attributes_to_include.get(attr, '').strip().lower() == text.strip().lower():
				del attributes_to_include[attr]

		if attributes_to_include:
			return ' '.join(f'{key}={cap_text_length(value, 100)}' for key, value in attributes_to_include.items())

		return ''
