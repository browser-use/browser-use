# @file purpose: Serializes enhanced DOM trees to HTML format including shadow roots

from browser_use.dom.views import EnhancedDOMTreeNode, NodeType


class HTMLSerializer:
	"""Serializes enhanced DOM trees back to HTML format.

	This serializer reconstructs HTML from the enhanced DOM tree, including:
	- Shadow DOM content (both open and closed)
	- Iframe content documents
	- All attributes and text nodes
	- Proper HTML structure

	Unlike getOuterHTML which only captures light DOM, this captures the full
	enhanced tree including shadow roots that are crucial for modern SPAs.
	"""

	def __init__(self, extract_links: bool = False):
		"""Initialize the HTML serializer.

		Args:
			extract_links: If True, preserves all links. If False, removes href attributes.
		"""
		self.extract_links = extract_links

	def serialize(self, node: EnhancedDOMTreeNode, depth: int = 0) -> str:
		"""Serialize an enhanced DOM tree node to HTML.

		Args:
			node: The enhanced DOM tree node to serialize
			depth: Current depth for indentation (internal use)

		Returns:
			HTML string representation of the node and its descendants
		"""
		if node.node_type == NodeType.DOCUMENT_NODE:
			# Process document root - serialize all children
			parts = []
			for child in node.children_and_shadow_roots:
				child_html = self.serialize(child, depth)
				if child_html:
					parts.append(child_html)
			return ''.join(parts)

		elif node.node_type == NodeType.DOCUMENT_FRAGMENT_NODE:
			# Shadow DOM root - wrap in template with shadowrootmode attribute
			parts = []

			# Add shadow root opening
			shadow_type = node.shadow_root_type or 'open'
			parts.append(f'<template shadowroot="{shadow_type.lower()}">')

			# Serialize shadow children
			for child in node.children:
				child_html = self.serialize(child, depth + 1)
				if child_html:
					parts.append(child_html)

			# Close shadow root
			parts.append('</template>')

			return ''.join(parts)

		elif node.node_type == NodeType.ELEMENT_NODE:
			parts = []
			tag_name = node.tag_name.lower()

			# Skip non-content elements
			if tag_name in {'style', 'script', 'head', 'meta', 'link', 'title'}:
				return ''

			# Skip code tags with display:none - these often contain JSON state for SPAs
			if tag_name == 'code' and node.attributes:
				style = node.attributes.get('style', '')
				# Check if element is hidden (display:none) - likely JSON data
				if 'display:none' in style.replace(' ', '') or 'display: none' in style:
					return ''
				# Also check for bpr-guid IDs (LinkedIn's JSON data pattern)
				element_id = node.attributes.get('id', '')
				if 'bpr-guid' in element_id or 'data' in element_id or 'state' in element_id:
					return ''

			# Skip base64 inline images - these are usually placeholders or tracking pixels
			if tag_name == 'img' and node.attributes:
				src = node.attributes.get('src', '')
				if src.startswith('data:image/'):
					return ''

			# Opening tag
			parts.append(f'<{tag_name}')

			# Add attributes
			if node.attributes:
				attrs = self._serialize_attributes(node.attributes)
				if attrs:
					parts.append(' ' + attrs)

			# Handle void elements (self-closing)
			void_elements = {
				'area',
				'base',
				'br',
				'col',
				'embed',
				'hr',
				'img',
				'input',
				'link',
				'meta',
				'param',
				'source',
				'track',
				'wbr',
			}
			if tag_name in void_elements:
				parts.append(' />')
				return ''.join(parts)

			parts.append('>')

			# Handle iframe content document
			if tag_name in {'iframe', 'frame'} and node.content_document:
				# Serialize iframe content
				for child in node.content_document.children_nodes or []:
					child_html = self.serialize(child, depth + 1)
					if child_html:
						parts.append(child_html)
			else:
				# Serialize shadow roots FIRST (for declarative shadow DOM)
				if node.shadow_roots:
					for shadow_root in node.shadow_roots:
						child_html = self.serialize(shadow_root, depth + 1)
						if child_html:
							parts.append(child_html)

				# Then serialize light DOM children (for slot projection)
				for child in node.children:
					child_html = self.serialize(child, depth + 1)
					if child_html:
						parts.append(child_html)

			# Closing tag
			parts.append(f'</{tag_name}>')

			return ''.join(parts)

		elif node.node_type == NodeType.TEXT_NODE:
			# Return text content with basic HTML escaping
			if node.node_value:
				return self._escape_html(node.node_value)
			return ''

		elif node.node_type == NodeType.COMMENT_NODE:
			# Skip comments to reduce noise
			return ''

		else:
			# Unknown node type - skip
			return ''

	def _serialize_attributes(self, attributes: dict[str, str]) -> str:
		"""Serialize element attributes to HTML attribute string.

		Args:
			attributes: Dictionary of attribute names to values

		Returns:
			HTML attribute string (e.g., 'class="foo" id="bar"')
		"""
		parts = []
		for key, value in attributes.items():
			# Skip href if not extracting links
			if not self.extract_links and key == 'href':
				continue

			# Skip data-* attributes as they often contain JSON payloads
			# These are used by modern SPAs (React, Vue, Angular) for state management
			if key.startswith('data-'):
				continue

			# Handle boolean attributes
			if value == '' or value is None:
				parts.append(key)
			else:
				# Escape attribute value
				escaped_value = self._escape_attribute(value)
				parts.append(f'{key}="{escaped_value}"')

		return ' '.join(parts)

	def _escape_html(self, text: str) -> str:
		"""Escape HTML special characters in text content.

		Args:
			text: Raw text content

		Returns:
			HTML-escaped text
		"""
		return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

	def _escape_attribute(self, value: str) -> str:
		"""Escape HTML special characters in attribute values.

		Args:
			value: Raw attribute value

		Returns:
			HTML-escaped attribute value
		"""
		return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#x27;')
