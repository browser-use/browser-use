from browser_use.dom.views import EnhancedDOMTreeNode, NodeType


class ClickableElementDetector:
	@staticmethod
	def is_interactive(node: EnhancedDOMTreeNode) -> bool:
		"""Check if this node is clickable/interactive using enhanced scoring."""

		# Skip non-element nodes
		if node.node_type != NodeType.ELEMENT_NODE:
			return False

		# # if ax ignored skip
		# if node.ax_node and node.ax_node.ignored:
		# 	return False

		# remove html and body nodes
		if node.tag_name in {'html', 'body'}:
			return False

		# RELAXED SIZE CHECK: Allow all elements including size 0 (they might be interactive overlays, etc.)
		# Note: Size 0 elements can still be interactive (e.g., invisible clickable overlays)
		# Visibility is determined separately by CSS styles, not just bounding box size

		# SEARCH ELEMENT DETECTION: Check for search-related classes and attributes
		if node.attributes:
			search_indicators = {
				'search',
				'magnify',
				'glass',
				'lookup',
				'find',
				'query',
				'search-icon',
				'search-btn',
				'search-button',
				'searchbox',
			}

			# Check class names for search indicators
			class_list = node.attributes.get('class', '').lower().split()
			if any(indicator in ' '.join(class_list) for indicator in search_indicators):
				return True

			# Check id for search indicators
			element_id = node.attributes.get('id', '').lower()
			if any(indicator in element_id for indicator in search_indicators):
				return True

			# Check data attributes for search functionality
			for attr_name, attr_value in node.attributes.items():
				if attr_name.startswith('data-') and any(indicator in attr_value.lower() for indicator in search_indicators):
					return True

		# Enhanced accessibility property checks - direct clear indicators only
		if node.ax_node and node.ax_node.properties:
			for prop in node.ax_node.properties:
				try:
					# aria disabled
					if prop.name == 'disabled' and prop.value:
						return False

					# aria hidden
					if prop.name == 'hidden' and prop.value:
						return False

					# Direct interactiveness indicators
					if prop.name in ['focusable', 'editable', 'settable'] and prop.value:
						return True

					# Interactive state properties (presence indicates interactive widget)
					if prop.name in ['checked', 'expanded', 'pressed', 'selected']:
						# These properties only exist on interactive elements
						return True

					# Form-related interactiveness
					if prop.name in ['required', 'autocomplete'] and prop.value:
						return True

					# Elements with keyboard shortcuts are interactive
					if prop.name == 'keyshortcuts' and prop.value:
						return True
				except (AttributeError, ValueError):
					# Skip properties we can't process
					continue

		# ENHANCED TAG CHECK: Include SVG and other common interactive elements
		interactive_tags = {
			'button',
			'input',
			'select',
			'textarea',
			'a',
			'label',
			'details',
			'summary',
			'option',
			'optgroup',
			'svg',
			'path',
			'circle',
			'rect',
			'polygon',
			'ellipse',
		}
		if node.tag_name in interactive_tags:
			return True

		# NAVIGATION ELEMENT CHECK: Include common navigation containers
		if node.tag_name in {'nav', 'header'} and node.attributes:
			# Navigation elements are often interactive if they have classes or roles
			if 'class' in node.attributes or 'role' in node.attributes:
				return True

		# Tertiary check: elements with interactive attributes
		if node.attributes:
			# Check for event handlers or interactive attributes
			interactive_attributes = {'onclick', 'onmousedown', 'onmouseup', 'onkeydown', 'onkeyup', 'tabindex'}
			if any(attr in node.attributes for attr in interactive_attributes):
				return True

			# Check for interactive ARIA roles
			if 'role' in node.attributes:
				interactive_roles = {
					'button',
					'link',
					'menuitem',
					'option',
					'radio',
					'checkbox',
					'tab',
					'textbox',
					'combobox',
					'slider',
					'spinbutton',
					'search',
					'searchbox',
				}
				if node.attributes['role'] in interactive_roles:
					return True

		# Quaternary check: accessibility tree roles
		if node.ax_node and node.ax_node.role:
			interactive_ax_roles = {
				'button',
				'link',
				'menuitem',
				'option',
				'radio',
				'checkbox',
				'tab',
				'textbox',
				'combobox',
				'slider',
				'spinbutton',
				'listbox',
				'search',
				'searchbox',
			}
			if node.ax_node.role in interactive_ax_roles:
				return True

		# ICON AND SMALL ELEMENT CHECK: Elements that might be icons
		if (
			node.snapshot_node
			and node.snapshot_node.bounds
			and 10 <= node.snapshot_node.bounds.width <= 50  # Icon-sized elements
			and 10 <= node.snapshot_node.bounds.height <= 50
		):
			# Check if this small element has interactive properties
			if node.attributes:
				# Small elements with these attributes are likely interactive icons
				icon_attributes = {'class', 'role', 'onclick', 'data-action', 'aria-label'}
				if any(attr in node.attributes for attr in icon_attributes):
					return True

		# Final fallback: cursor style indicates interactivity (for cases Chrome missed)
		if node.snapshot_node and node.snapshot_node.cursor_style and node.snapshot_node.cursor_style == 'pointer':
			return True

		return False
