from browser_use.dom.views import EnhancedDOMTreeNode, NodeType


class ClickableElementDetector:
	@staticmethod
	def _has_visible_size(node: EnhancedDOMTreeNode) -> bool:
		"""
		Check if node has non-zero dimensions (not collapsed/hidden).
		Returns:
			True if element has visible size (width > 0 and height > 0)
			True if no bounds info available (assume visible)
			False if element has zero width or height
		"""
		if not (node.snapshot_node and node.snapshot_node.bounds):
			return True  # No bounds info, assume visible
		bounds = node.snapshot_node.bounds
		return bounds.height > 0 and bounds.width > 0
	@staticmethod
	def _check_accessibility_properties(node: EnhancedDOMTreeNode) -> bool:
		"""
		Enhanced accessibility property checks with comprehensive coverage.
		Returns:
			True if interactive based on accessibility properties
			False if not interactive or no conclusive determination
		"""
		if not (node.ax_node and node.ax_node.properties):
			return False
		if node.ax_node.ignored:  # all ignored nodes are not interactive
			return False

		for prop in node.ax_node.properties:
			try:
				# TIER 1: Always interactive (strong indicators)
				# Direct interaction capabilities
				if prop.name in ['focusable', 'editable', 'settable'] and prop.value:
					return True

				# Widget states (only interactive elements have these)
				if prop.name in ['checked', 'expanded', 'pressed', 'selected']:
					# These properties only exist on interactive elements
					return True

				# EXCLUSION RULES: These properties prevent interactivity
				if prop.name == 'disabled' and prop.value:
					return False
				# if prop.name == 'hidden' and prop.value:
				# 	return False
				# if prop.name == 'hiddenRoot' and prop.value:
				# 	return False
				if prop.name == 'readonly' and prop.value:
					return False
				if prop.name == 'busy' and prop.value:
					return False

				# Interactive widget attributes
				if prop.name == 'hasPopup' and prop.value:
					return True
				if prop.name == 'multiselectable' and prop.value:
					return True

				# TIER 2: Contextually interactive (moderate indicators)
				# Form/input related
				if prop.name in ['required', 'autocomplete'] and prop.value:
					return True
				if prop.name in ['valuemin', 'valuemax', 'valuetext'] and prop.value:
					return True

				# Elements with keyboard shortcuts are interactive
				if prop.name == 'keyshortcuts' and prop.value:
					return True

			except (AttributeError, ValueError):
				# Skip properties we can't process
				continue
		return False

	@staticmethod
	def _has_event_handlers_or_interactive_attributes(node: EnhancedDOMTreeNode) -> bool:
		"""
		Check for event handlers or interactive attributes.
		Returns:
			True if node has event handlers or interactive attributes
		"""
		if not node.attributes:
			return False
		# Event handlers and interactive attributes
		event_handlers_and_interactive_attrs = {
			# Event handlers
			'onclick',
			'onmousedown',
			'onmouseup',
			'onkeydown',
			'onkeyup',
			# Interactive attributes
			'tabindex',
			'contenteditable',
		}
		return any(attr in node.attributes for attr in event_handlers_and_interactive_attrs)

	@staticmethod
	def _has_interactive_cursor(node: EnhancedDOMTreeNode) -> bool:
		"""
		Enhanced cursor style detection.
		Returns:
			True if node has an interactive cursor style
		"""
		if not (node.snapshot_node and node.snapshot_node.cursor_style):
			return False
		interactive_cursors = {
			'pointer',
			'move',
			'text',
			'grab',
			'grabbing',
			'cell',
			'copy',
			'alias',
			'all-scroll',
			'col-resize',
			'context-menu',
			'crosshair',
			'help',
			'zoom-in',
			'zoom-out',
		}
		return node.snapshot_node.cursor_style in interactive_cursors

	@staticmethod
	def is_interactive(node: EnhancedDOMTreeNode) -> bool:
		"""Check if this node is clickable/interactive using enhanced scoring."""

		# Skip non-element nodes
		if node.node_type != NodeType.ELEMENT_NODE:
			return False

		# remove html and body nodes
		if node.tag_name in {'html', 'body'}:
			return False
		
		# IFRAME elements should be interactive if they're large enough to potentially need scrolling
		# Small iframes (< 100px width or height) are unlikely to have scrollable content
		if node.tag_name and node.tag_name.upper() == 'IFRAME':
			if node.snapshot_node and node.snapshot_node.bounds:
				width = node.snapshot_node.bounds.width
				height = node.snapshot_node.bounds.height
				# Only include iframes larger than 100x100px
				if width > 100 and height > 100:
					return True

		# Skip elements with zero height or width (collapsed/hidden elements)
		# These are often dropdown menus or expandable content that's not currently visible
		if not ClickableElementDetector._has_visible_size(node):
			return False

		# Check accessibility properties
		if ClickableElementDetector._check_accessibility_properties(node):
			return True

		# Enhanced tag check: Include truly interactive elements
		# interactive_tags = {
		# 	'button',
		# 	'input',
		# 	'select',
		# 	'textarea',
		# 	'a',
		# 	'label',
		# 	'details',
		# 	'summary',
		# 	'option',
		# 	'optgroup',
		# }
		# if node.tag_name in interactive_tags:
		# 	return True

		# Check for event handlers or interactive attributes
		if ClickableElementDetector._has_event_handlers_or_interactive_attributes(node):
			return True

		# Accessibility tree roles (fallback check)
		# if node.ax_node and node.ax_node.role:
		# 	interactive_ax_roles = {
		# 		'button',
		# 		'link',
		# 		'menuitem',
		# 		'option',
		# 		'radio',
		# 		'checkbox',
		# 		'tab',
		# 		'textbox',
		# 		'combobox',
		# 		'slider',
		# 		'spinbutton',
		# 		'listbox',
		# 		'search',
		# 		'searchbox',
		# 		'switch',
		# 	}
		# 	if node.ax_node.role in interactive_ax_roles:
		# 		return True

		# Check cursor style
		if ClickableElementDetector._has_interactive_cursor(node):
			return True

		return False
