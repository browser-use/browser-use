# @file purpose: SOTA content extraction that preserves structure and element indices
"""
Content Extractor - Structured extraction that correlates with browser_state.

Based on research from:
- D2Snap: DOM downsampling with 96% size reduction while maintaining 67% task success
- AgentOccam: Pivotal node filtering with hierarchy preservation
- Playwright MCP: Accessibility-tree-first representation

Key insight: Extraction should EXTEND browser_state, not replace it with prose.
The agent needs to correlate what it reads with what it can click.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from browser_use.dom.views import (
	DEFAULT_INCLUDE_ATTRIBUTES,
	DOMSelectorMap,
	EnhancedDOMTreeNode,
	NodeType,
	SimplifiedNode,
)

if TYPE_CHECKING:
	from browser_use.dom.views import SerializedDOMState


# Content-bearing tags that should include their text
CONTENT_TAGS = frozenset({
	'p', 'span', 'div', 'li', 'td', 'th', 'dd', 'dt',
	'label', 'legend', 'caption', 'figcaption',
	'blockquote', 'pre', 'code', 'cite', 'q',
})

# Structural tags that define document sections
SECTION_TAGS = frozenset({
	'main', 'article', 'section', 'aside', 'nav',
	'header', 'footer', 'form', 'fieldset',
})

# Heading tags
HEADING_TAGS = frozenset({'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})

# List container tags
LIST_TAGS = frozenset({'ul', 'ol', 'dl', 'menu'})

# Table structure tags
TABLE_TAGS = frozenset({'table', 'thead', 'tbody', 'tfoot', 'tr'})

# Skip these entirely
SKIP_TAGS = frozenset({
	'script', 'style', 'noscript', 'template', 'slot',
	'svg', 'path', 'meta', 'link', 'head',
})


@dataclass
class ExtractedSection:
	"""A section of extracted content with context."""

	role: str  # 'main', 'article', 'form', 'navigation', etc.
	heading: str | None  # Section heading if any
	content_lines: list[str] = field(default_factory=list)
	interactive_indices: list[int] = field(default_factory=list)  # backend_node_ids of interactive elements
	subsections: list['ExtractedSection'] = field(default_factory=list)


@dataclass
class ExtractionResult:
	"""Result of structured content extraction."""

	sections: list[ExtractedSection]
	total_text_chars: int
	total_interactive_elements: int
	main_content_found: bool
	extraction_method: str

	def to_structured_text(self, max_chars: int = 50000) -> str:
		"""Convert to structured text format that preserves indices."""
		lines = []
		char_count = 0

		for section in self.sections:
			section_lines = self._format_section(section, depth=0)
			for line in section_lines:
				if char_count + len(line) > max_chars:
					lines.append(f'\n[Content truncated at {char_count:,} chars - {max_chars - char_count:,} chars remaining]')
					return '\n'.join(lines)
				lines.append(line)
				char_count += len(line) + 1

		return '\n'.join(lines)

	def _format_section(self, section: ExtractedSection, depth: int) -> list[str]:
		"""Format a section with proper indentation."""
		lines = []
		indent = '  ' * depth

		# Section header
		if section.heading:
			lines.append(f'{indent}## {section.heading}')
		elif section.role and section.role not in ('unknown', 'generic'):
			lines.append(f'{indent}[{section.role}]')

		# Content lines
		for line in section.content_lines:
			if line.strip():
				lines.append(f'{indent}{line}')

		# Subsections
		for subsection in section.subsections:
			lines.extend(self._format_section(subsection, depth + 1))

		return lines


class ContentExtractor:
	"""
	Extracts page content while preserving structure and element indices.

	Unlike the old HTMLSerializer→markdownify approach, this:
	1. Preserves element indices (backend_node_id) for correlation with browser_state
	2. Uses accessibility tree roles for semantic sections
	3. Maintains hierarchy for LLM understanding
	4. Groups content around interactive elements (pivotal nodes)
	"""

	def __init__(
		self,
		selector_map: DOMSelectorMap,
		include_navigation: bool = False,
		include_complementary: bool = False,
		max_text_per_element: int = 500,
	):
		"""
		Initialize content extractor.

		Args:
			selector_map: Map of backend_node_id → EnhancedDOMTreeNode for interactive elements
			include_navigation: Include navigation regions
			include_complementary: Include sidebar/complementary regions
			max_text_per_element: Max chars of text to include per element
		"""
		self.selector_map = selector_map
		self.include_navigation = include_navigation
		self.include_complementary = include_complementary
		self.max_text_per_element = max_text_per_element

		# Build reverse lookup: which elements are interactive
		self._interactive_ids = set(selector_map.keys())

	def extract(self, root: EnhancedDOMTreeNode) -> ExtractionResult:
		"""
		Extract structured content from DOM tree.

		Args:
			root: Root of the enhanced DOM tree

		Returns:
			ExtractionResult with sections preserving structure and indices
		"""
		sections = []
		total_chars = 0
		main_found = False

		# Find main content region first
		main_node = self._find_main_content(root)
		if main_node:
			main_found = True
			main_section = self._extract_section(main_node, 'main')
			if main_section:
				sections.append(main_section)
				total_chars += self._count_chars(main_section)

		# If no main content, extract from body
		if not sections:
			body = self._find_body(root)
			if body:
				body_section = self._extract_section(body, 'page')
				if body_section:
					sections.append(body_section)
					total_chars += self._count_chars(body_section)

		return ExtractionResult(
			sections=sections,
			total_text_chars=total_chars,
			total_interactive_elements=len(self._interactive_ids),
			main_content_found=main_found,
			extraction_method='structured_accessibility',
		)

	def _find_main_content(self, node: EnhancedDOMTreeNode) -> EnhancedDOMTreeNode | None:
		"""Find main content region using accessibility tree."""
		if node.node_type != NodeType.ELEMENT_NODE and node.node_type != NodeType.DOCUMENT_NODE:
			return None

		# Check ARIA role
		role = self._get_role(node)
		if role == 'main':
			return node

		# Check tag name
		tag = node.tag_name.lower() if node.node_type == NodeType.ELEMENT_NODE else ''
		if tag == 'main':
			return node

		# Check article as fallback
		if tag == 'article' or role == 'article':
			return node

		# Recurse into children
		for child in node.children:
			result = self._find_main_content(child)
			if result:
				return result

		# Check shadow roots
		if node.shadow_roots:
			for shadow in node.shadow_roots:
				result = self._find_main_content(shadow)
				if result:
					return result

		return None

	def _find_body(self, node: EnhancedDOMTreeNode) -> EnhancedDOMTreeNode | None:
		"""Find body element."""
		if node.node_type == NodeType.ELEMENT_NODE and node.tag_name.lower() == 'body':
			return node

		for child in node.children:
			result = self._find_body(child)
			if result:
				return result

		return None

	def _get_role(self, node: EnhancedDOMTreeNode) -> str | None:
		"""Get semantic role from accessibility tree or attributes."""
		# Check AX tree first
		if node.ax_node and node.ax_node.role:
			return node.ax_node.role.lower()

		# Check role attribute
		if node.attributes:
			role = node.attributes.get('role', '').lower()
			if role:
				return role

		return None

	def _should_skip_region(self, node: EnhancedDOMTreeNode) -> bool:
		"""Check if region should be skipped based on role."""
		role = self._get_role(node)
		tag = node.tag_name.lower() if node.node_type == NodeType.ELEMENT_NODE else ''

		# Skip navigation unless explicitly included
		if not self.include_navigation:
			if role == 'navigation' or tag == 'nav':
				return True

		# Skip complementary/aside unless included
		if not self.include_complementary:
			if role == 'complementary' or tag == 'aside':
				return True

		# Skip banner/footer boilerplate
		if role in ('banner', 'contentinfo') or tag in ('header', 'footer'):
			# But include if they contain forms (login forms often in header)
			if self._has_form_descendant(node):
				return False
			return True

		return False

	def _has_form_descendant(self, node: EnhancedDOMTreeNode) -> bool:
		"""Check if node has a form descendant."""
		if node.node_type == NodeType.ELEMENT_NODE:
			if node.tag_name.lower() == 'form' or self._get_role(node) == 'form':
				return True

		for child in node.children:
			if self._has_form_descendant(child):
				return True

		return False

	def _extract_section(self, node: EnhancedDOMTreeNode, default_role: str) -> ExtractedSection | None:
		"""Extract a section with its content and subsections."""
		if node.node_type not in (NodeType.ELEMENT_NODE, NodeType.DOCUMENT_NODE, NodeType.DOCUMENT_FRAGMENT_NODE):
			return None

		tag = node.tag_name.lower() if node.node_type == NodeType.ELEMENT_NODE else ''

		# Skip non-content tags
		if tag in SKIP_TAGS:
			return None

		# Check if this region should be skipped
		if self._should_skip_region(node):
			return None

		role = self._get_role(node) or default_role
		heading = self._find_section_heading(node)

		section = ExtractedSection(
			role=role,
			heading=heading,
		)

		# Process children
		self._process_children(node, section)

		# Only return if there's actual content
		if section.content_lines or section.subsections or section.interactive_indices:
			return section

		return None

	def _find_section_heading(self, node: EnhancedDOMTreeNode) -> str | None:
		"""Find the first heading in a section."""
		if node.node_type != NodeType.ELEMENT_NODE:
			return None

		tag = node.tag_name.lower()
		if tag in HEADING_TAGS:
			return self._get_text_content(node, max_length=100)

		# Check immediate children for headings
		for child in node.children[:5]:  # Only check first few children
			if child.node_type == NodeType.ELEMENT_NODE and child.tag_name.lower() in HEADING_TAGS:
				return self._get_text_content(child, max_length=100)

		return None

	def _process_children(self, node: EnhancedDOMTreeNode, section: ExtractedSection) -> None:
		"""Process children and add content/subsections."""
		for child in node.children:
			self._process_node(child, section)

		# Also process shadow roots
		if node.shadow_roots:
			for shadow in node.shadow_roots:
				for child in shadow.children:
					self._process_node(child, section)

	def _process_node(self, node: EnhancedDOMTreeNode, section: ExtractedSection) -> None:
		"""Process a node and add to section."""
		if node.node_type == NodeType.TEXT_NODE:
			text = (node.node_value or '').strip()
			if text and len(text) > 1:
				section.content_lines.append(text)
			return

		if node.node_type != NodeType.ELEMENT_NODE:
			# For document fragments (shadow roots), process children
			if node.node_type == NodeType.DOCUMENT_FRAGMENT_NODE:
				for child in node.children:
					self._process_node(child, section)
			return

		tag = node.tag_name.lower()

		# Skip non-content tags
		if tag in SKIP_TAGS:
			return

		# Skip hidden elements
		if not node.is_visible and tag not in ('input',):  # Keep hidden inputs
			return

		# Check if this is an interactive element
		is_interactive = node.backend_node_id in self._interactive_ids

		# Handle different element types
		if tag in SECTION_TAGS:
			# Create subsection
			subsection = self._extract_section(node, tag)
			if subsection:
				section.subsections.append(subsection)

		elif tag in HEADING_TAGS:
			# Add heading with level indicator
			text = self._get_text_content(node, max_length=200)
			if text:
				level = int(tag[1])  # h1 -> 1, h2 -> 2, etc.
				prefix = '#' * level
				section.content_lines.append(f'{prefix} {text}')

		elif is_interactive:
			# Interactive element - show with index for correlation
			line = self._format_interactive_element(node)
			section.content_lines.append(line)
			section.interactive_indices.append(node.backend_node_id)

		elif tag in CONTENT_TAGS:
			# Content element - include text
			text = self._get_text_content(node, max_length=self.max_text_per_element)
			if text:
				section.content_lines.append(text)

		elif tag in LIST_TAGS:
			# List container - process items
			self._process_list(node, section)

		elif tag in TABLE_TAGS or tag == 'table':
			# Table - format as markdown table
			table_text = self._format_table(node)
			if table_text:
				section.content_lines.append(table_text)

		else:
			# Generic container - recurse into children
			self._process_children(node, section)

	def _format_interactive_element(self, node: EnhancedDOMTreeNode) -> str:
		"""Format an interactive element with its index and key attributes."""
		tag = node.tag_name.lower()
		parts = [f'[{node.backend_node_id}]<{tag}']

		# Add key attributes
		attrs = node.attributes or {}

		# Type for inputs
		if 'type' in attrs:
			parts.append(f' type={attrs["type"]}')

		# Name/id for forms
		if 'name' in attrs:
			parts.append(f' name={attrs["name"]}')
		elif 'id' in attrs:
			parts.append(f' id={attrs["id"]}')

		# Current value
		if 'value' in attrs and attrs['value']:
			value = attrs['value'][:50]
			parts.append(f' value="{value}"')

		# Placeholder
		if 'placeholder' in attrs:
			parts.append(f' placeholder="{attrs["placeholder"][:30]}"')

		# Aria label
		if 'aria-label' in attrs:
			parts.append(f' aria-label="{attrs["aria-label"][:50]}"')

		parts.append('>')

		# Add visible text content
		text = self._get_text_content(node, max_length=50)
		if text:
			parts.append(text)

		parts.append(f'</{tag}>')

		return ''.join(parts)

	def _process_list(self, node: EnhancedDOMTreeNode, section: ExtractedSection) -> None:
		"""Process a list and its items."""
		tag = node.tag_name.lower()
		is_ordered = tag == 'ol'

		item_num = 1
		for child in node.children:
			if child.node_type != NodeType.ELEMENT_NODE:
				continue

			child_tag = child.tag_name.lower()
			if child_tag in ('li', 'dt', 'dd'):
				prefix = f'{item_num}.' if is_ordered else '-'

				# Check if list item contains interactive elements
				if child.backend_node_id in self._interactive_ids:
					line = f'{prefix} {self._format_interactive_element(child)}'
				else:
					text = self._get_text_content(child, max_length=200)
					line = f'{prefix} {text}' if text else None

				if line:
					section.content_lines.append(line)
					if child.backend_node_id in self._interactive_ids:
						section.interactive_indices.append(child.backend_node_id)

				if is_ordered:
					item_num += 1

	def _format_table(self, node: EnhancedDOMTreeNode) -> str:
		"""Format a table as markdown."""
		rows = []

		def find_rows(n: EnhancedDOMTreeNode) -> None:
			if n.node_type == NodeType.ELEMENT_NODE and n.tag_name.lower() == 'tr':
				rows.append(n)
			else:
				for child in n.children:
					find_rows(child)

		find_rows(node)

		if not rows:
			return ''

		lines = []
		for i, row in enumerate(rows[:20]):  # Limit to 20 rows
			cells = []
			for child in row.children:
				if child.node_type == NodeType.ELEMENT_NODE and child.tag_name.lower() in ('td', 'th'):
					# Check for interactive elements in cell
					if child.backend_node_id in self._interactive_ids:
						cells.append(self._format_interactive_element(child))
					else:
						text = self._get_text_content(child, max_length=50)
						cells.append(text or '')

			if cells:
				lines.append('| ' + ' | '.join(cells) + ' |')
				# Add separator after header row
				if i == 0:
					lines.append('| ' + ' | '.join(['---'] * len(cells)) + ' |')

		return '\n'.join(lines)

	def _get_text_content(self, node: EnhancedDOMTreeNode, max_length: int = 200) -> str:
		"""Get text content from a node and its descendants."""
		parts = []

		def collect(n: EnhancedDOMTreeNode, depth: int = 0) -> None:
			if depth > 10:  # Prevent infinite recursion
				return

			if n.node_type == NodeType.TEXT_NODE:
				text = (n.node_value or '').strip()
				if text:
					parts.append(text)
			elif n.node_type == NodeType.ELEMENT_NODE:
				# Skip script/style content
				if n.tag_name.lower() in SKIP_TAGS:
					return
				for child in n.children:
					collect(child, depth + 1)

		collect(node)

		text = ' '.join(parts)
		if len(text) > max_length:
			text = text[:max_length - 3] + '...'

		return text

	def _count_chars(self, section: ExtractedSection) -> int:
		"""Count total characters in a section."""
		count = sum(len(line) for line in section.content_lines)
		for sub in section.subsections:
			count += self._count_chars(sub)
		return count


def extract_structured_content(
	root: EnhancedDOMTreeNode,
	selector_map: DOMSelectorMap,
	include_navigation: bool = False,
	include_complementary: bool = False,
	max_chars: int = 50000,
) -> tuple[str, dict[str, Any]]:
	"""
	Extract structured content from DOM tree.

	This is the main entry point for the new SOTA extraction approach.
	Unlike the old HTML→markdown pipeline, this preserves:
	- Element indices for correlation with browser_state
	- Semantic structure from accessibility tree
	- Hierarchy that helps LLM understand page layout

	Args:
		root: Enhanced DOM tree root
		selector_map: Map of interactive elements
		include_navigation: Include nav regions
		include_complementary: Include sidebars
		max_chars: Maximum output characters

	Returns:
		tuple: (structured_text, extraction_stats)
	"""
	extractor = ContentExtractor(
		selector_map=selector_map,
		include_navigation=include_navigation,
		include_complementary=include_complementary,
	)

	result = extractor.extract(root)
	content = result.to_structured_text(max_chars=max_chars)

	stats = {
		'total_text_chars': result.total_text_chars,
		'total_interactive_elements': result.total_interactive_elements,
		'main_content_found': result.main_content_found,
		'extraction_method': result.extraction_method,
		'section_count': len(result.sections),
	}

	return content, stats
