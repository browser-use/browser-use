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

		# Primary check: Chrome's own clickable detection (most reliable for DIV buttons, etc.)
		# if node.snapshot_node and node.snapshot_node.is_clickable:
		# 	return True
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

		# Secondary check: intrinsically interactive HTML elements
		# Note: iframe is removed - only iframe content should be interactive, not the iframe container
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
		}
		if node.tag_name in interactive_tags:
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
			}
			if node.ax_node.role in interactive_ax_roles:
				return True

		# Final fallback: cursor style indicates interactivity (for cases Chrome missed)
		if node.snapshot_node and node.snapshot_node.cursor_style and node.snapshot_node.cursor_style == 'pointer':
			return True

		return False
