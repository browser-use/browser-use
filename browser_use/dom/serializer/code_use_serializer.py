# @file purpose: Ultra-compact serializer optimized for code-use agents
# Focuses on minimal token usage while preserving essential interactive context

from browser_use.dom.utils import cap_text_length
from browser_use.dom.views import (
	EnhancedDOMTreeNode,
	NodeType,
	SimplifiedNode,
)

# Minimal but sufficient attribute list for code agents
CODE_USE_KEY_ATTRIBUTES = [
	'id',  # Essential for element selection
	'name',  # For form inputs
	'type',  # For input types
	'placeholder',  # For empty inputs
	'aria-label',  # For buttons without text
	'value',  # Current values
	'alt',  # For images
	'class',  # Keep top 2 classes for common selectors
]

# Interactive elements agent can use
INTERACTIVE_ELEMENTS = {
	'a',
	'button',
	'input',
	'textarea',
	'select',
	'form',
}

# Semantic structure elements - expanded to include more content containers
SEMANTIC_STRUCTURE = {
	'h1',
	'h2',
	'h3',
	'h4',
	'h5',
	'h6',
	'nav',
	'main',
	'header',
	'footer',
	'article',
	'section',
	'p',  # Paragraphs often contain prices and product info
	'span',  # Spans often contain prices and labels
	'div',  # Divs with useful attributes (id/class) should be shown
	'ul',
	'ol',
	'li',
	'label',
	'img',
}


class DOMCodeAgentSerializer:
	"""Optimized DOM serializer for code-use agents - balances token efficiency with context."""

	@staticmethod
	def serialize_tree(node: SimplifiedNode | None, include_attributes: list[str], depth: int = 0) -> str:
		"""
		Serialize DOM tree with smart token optimization.

		Strategy:
		- Keep top 2 CSS classes for querySelector compatibility
		- Show div/span/p elements with useful attributes or text
		- Show all interactive + semantic elements
		- Inline text up to 80 chars for better context
		"""
		if not node:
			return ''

		# Skip excluded/hidden nodes
		if hasattr(node, 'excluded_by_parent') and node.excluded_by_parent:
			return DOMCodeAgentSerializer._serialize_children(node, include_attributes, depth)

		if not node.should_display:
			return DOMCodeAgentSerializer._serialize_children(node, include_attributes, depth)

		formatted_text = []
		depth_str = '  ' * depth  # Use 2 spaces instead of tabs for compactness

		if node.original_node.node_type == NodeType.ELEMENT_NODE:
			tag = node.original_node.tag_name.lower()
			is_visible = node.original_node.snapshot_node and node.original_node.is_visible

			# Skip invisible (except iframes)
			if not is_visible and tag not in ['iframe', 'frame']:
				return DOMCodeAgentSerializer._serialize_children(node, include_attributes, depth)

			# Special handling for iframes
			if tag in ['iframe', 'frame']:
				return DOMCodeAgentSerializer._serialize_iframe(node, include_attributes, depth)

			# Build minimal attributes
			attributes_str = DOMCodeAgentSerializer._build_minimal_attributes(node.original_node)

			# Decide if element should be shown
			is_interactive = tag in INTERACTIVE_ELEMENTS
			is_semantic = tag in SEMANTIC_STRUCTURE
			has_useful_attrs = bool(attributes_str)
			has_text = DOMCodeAgentSerializer._has_direct_text(node)

			# Skip non-semantic, non-interactive containers without attributes
			if not is_interactive and not is_semantic and not has_useful_attrs and not has_text:
				return DOMCodeAgentSerializer._serialize_children(node, include_attributes, depth)

			# Collapse pointless wrappers
			if tag in {'div', 'span'} and not has_useful_attrs and not has_text and len(node.children) == 1:
				return DOMCodeAgentSerializer._serialize_children(node, include_attributes, depth)

			# Build element
			line = f'{depth_str}<{tag}'

			if attributes_str:
				line += f' {attributes_str}'

			# Inline text
			inline_text = DOMCodeAgentSerializer._get_inline_text(node)
			if inline_text:
				line += f'>{inline_text}'
			else:
				line += '>'

			formatted_text.append(line)

			# Children (only if no inline text)
			if node.children and not inline_text:
				children_text = DOMCodeAgentSerializer._serialize_children(node, include_attributes, depth + 1)
				if children_text:
					formatted_text.append(children_text)

		elif node.original_node.node_type == NodeType.TEXT_NODE:
			# Handled inline with parent
			pass

		elif node.original_node.node_type == NodeType.DOCUMENT_FRAGMENT_NODE:
			# Shadow DOM - minimal marker
			if node.children:
				formatted_text.append(f'{depth_str}#shadow')
				children_text = DOMCodeAgentSerializer._serialize_children(node, include_attributes, depth + 1)
				if children_text:
					formatted_text.append(children_text)

		return '\n'.join(formatted_text)

	@staticmethod
	def _serialize_children(node: SimplifiedNode, include_attributes: list[str], depth: int) -> str:
		"""Serialize children."""
		children_output = []
		for child in node.children:
			child_text = DOMCodeAgentSerializer.serialize_tree(child, include_attributes, depth)
			if child_text:
				children_output.append(child_text)
		return '\n'.join(children_output)

	@staticmethod
	def _build_minimal_attributes(node: EnhancedDOMTreeNode) -> str:
		"""Build minimal but useful attributes - keep top 2 classes for selectors."""
		attrs = []

		if node.attributes:
			for attr in CODE_USE_KEY_ATTRIBUTES:
				if attr in node.attributes:
					value = str(node.attributes[attr]).strip()
					if value:
						# Special handling for class - keep only first 2 classes
						if attr == 'class':
							classes = value.split()[:2]
							value = ' '.join(classes)
						# Cap at 25 chars
						value = cap_text_length(value, 25)
						attrs.append(f'{attr}="{value}"')

		return ' '.join(attrs)

	@staticmethod
	def _has_direct_text(node: SimplifiedNode) -> bool:
		"""Check if node has direct text children."""
		for child in node.children:
			if child.original_node.node_type == NodeType.TEXT_NODE:
				text = child.original_node.node_value.strip() if child.original_node.node_value else ''
				if len(text) > 1:
					return True
		return False

	@staticmethod
	def _get_inline_text(node: SimplifiedNode) -> str:
		"""Get inline text (max 80 chars for better context)."""
		text_parts = []
		for child in node.children:
			if child.original_node.node_type == NodeType.TEXT_NODE:
				text = child.original_node.node_value.strip() if child.original_node.node_value else ''
				if text and len(text) > 1:
					text_parts.append(text)

		if not text_parts:
			return ''

		combined = ' '.join(text_parts)
		return cap_text_length(combined, 40)

	@staticmethod
	def _serialize_iframe(node: SimplifiedNode, include_attributes: list[str], depth: int) -> str:
		"""Handle iframe minimally."""
		formatted_text = []
		depth_str = '  ' * depth
		tag = node.original_node.tag_name.lower()

		# Minimal iframe marker
		attributes_str = DOMCodeAgentSerializer._build_minimal_attributes(node.original_node)
		line = f'{depth_str}<{tag}'
		if attributes_str:
			line += f' {attributes_str}'
		line += '>'
		formatted_text.append(line)

		# Iframe content
		if node.original_node.content_document:
			formatted_text.append(f'{depth_str}  #iframe-content')

			# Find and serialize body content only
			for child_node in node.original_node.content_document.children_nodes or []:
				if child_node.tag_name.lower() == 'html':
					for html_child in child_node.children:
						if html_child.tag_name.lower() == 'body':
							for body_child in html_child.children:
								DOMCodeAgentSerializer._serialize_document_node(
									body_child, formatted_text, include_attributes, depth + 2
								)
							break

		return '\n'.join(formatted_text)

	@staticmethod
	def _serialize_document_node(
		dom_node: EnhancedDOMTreeNode, output: list[str], include_attributes: list[str], depth: int
	) -> None:
		"""Serialize document node without SimplifiedNode wrapper."""
		depth_str = '  ' * depth

		if dom_node.node_type == NodeType.ELEMENT_NODE:
			tag = dom_node.tag_name.lower()

			# Skip invisible
			is_visible = dom_node.snapshot_node and dom_node.is_visible
			if not is_visible:
				return

			# Check if worth showing
			is_interactive = tag in INTERACTIVE_ELEMENTS
			is_semantic = tag in SEMANTIC_STRUCTURE
			attributes_str = DOMCodeAgentSerializer._build_minimal_attributes(dom_node)

			if not is_interactive and not is_semantic and not attributes_str:
				# Skip but process children
				for child in dom_node.children:
					DOMCodeAgentSerializer._serialize_document_node(child, output, include_attributes, depth)
				return

			# Build element
			line = f'{depth_str}<{tag}'
			if attributes_str:
				line += f' {attributes_str}'

			# Get text
			text_parts = []
			for child in dom_node.children:
				if child.node_type == NodeType.TEXT_NODE and child.node_value:
					text = child.node_value.strip()
					if text and len(text) > 1:
						text_parts.append(text)

			if text_parts:
				combined = ' '.join(text_parts)
				line += f'>{cap_text_length(combined, 25)}'
			else:
				line += '>'

			output.append(line)

			# Process non-text children
			for child in dom_node.children:
				if child.node_type != NodeType.TEXT_NODE:
					DOMCodeAgentSerializer._serialize_document_node(child, output, include_attributes, depth + 1)
