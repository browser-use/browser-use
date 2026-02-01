"""Tests for SOTA content extractor that preserves element indices."""

from dataclasses import dataclass, field

import pytest

from browser_use.dom.extraction import (
	ContentExtractor,
	ExtractedSection,
	ExtractionResult,
	extract_structured_content,
)
from browser_use.dom.views import (
	DOMSelectorMap,
	NodeType,
)


@dataclass
class MockAXNode:
	"""Mock accessibility node."""

	role: str | None = None


@dataclass
class MockDOMNode:
	"""Mock DOM node for testing the content extractor.

	This simplifies the EnhancedDOMTreeNode interface to just the fields
	the ContentExtractor actually uses.
	"""

	node_type: NodeType
	node_name: str
	backend_node_id: int = 0
	node_value: str = ''
	attributes: dict[str, str] = field(default_factory=dict)
	is_visible: bool = True
	children_nodes: list['MockDOMNode'] = field(default_factory=list)
	shadow_roots: list['MockDOMNode'] | None = None
	ax_node: MockAXNode | None = None

	@property
	def tag_name(self) -> str:
		return self.node_name.lower()

	@property
	def children(self) -> list['MockDOMNode']:
		return self.children_nodes


def create_element_node(
	tag_name: str,
	backend_node_id: int,
	children: list[MockDOMNode] | None = None,
	attributes: dict[str, str] | None = None,
	is_visible: bool = True,
	role: str | None = None,
) -> MockDOMNode:
	"""Create a mock element node for testing."""
	return MockDOMNode(
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag_name,
		backend_node_id=backend_node_id,
		children_nodes=children or [],
		attributes=attributes or {},
		is_visible=is_visible,
		ax_node=MockAXNode(role=role) if role else None,
	)


def create_text_node(text: str) -> MockDOMNode:
	"""Create a mock text node for testing."""
	return MockDOMNode(
		node_type=NodeType.TEXT_NODE,
		node_name='#text',
		node_value=text,
		backend_node_id=0,
	)


class TestContentExtractor:
	"""Tests for ContentExtractor class."""

	def test_extracts_interactive_elements_with_indices(self):
		"""Interactive elements should be formatted with their backend_node_id."""
		# Create a button element
		button_text = create_text_node('Submit')
		button = create_element_node(
			'button',
			backend_node_id=123,
			children=[button_text],
			attributes={'type': 'submit'},
		)

		# Create body with button
		body = create_element_node('body', backend_node_id=1, children=[button])

		# Create selector map with button as interactive
		selector_map: DOMSelectorMap = {123: button}  # type: ignore

		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		# Check that content includes the indexed element
		content = result.to_structured_text()
		assert '[123]<button' in content
		assert 'Submit' in content

	def test_extracts_text_content(self):
		"""Text content should be extracted from content tags."""
		text = create_text_node('This is paragraph content.')
		p = create_element_node('p', backend_node_id=10, children=[text])
		body = create_element_node('body', backend_node_id=1, children=[p])

		selector_map: DOMSelectorMap = {}
		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		content = result.to_structured_text()
		assert 'This is paragraph content.' in content

	def test_extracts_headings_with_level(self):
		"""Headings should include their level indicator."""
		h1_text = create_text_node('Main Title')
		h1 = create_element_node('h1', backend_node_id=10, children=[h1_text])
		h2_text = create_text_node('Subtitle')
		h2 = create_element_node('h2', backend_node_id=11, children=[h2_text])

		body = create_element_node('body', backend_node_id=1, children=[h1, h2])

		selector_map: DOMSelectorMap = {}
		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		content = result.to_structured_text()
		assert '# Main Title' in content
		assert '## Subtitle' in content

	def test_skips_navigation_by_default(self):
		"""Navigation regions should be skipped by default."""
		nav_text = create_text_node('Home | About | Contact')
		nav = create_element_node(
			'nav',
			backend_node_id=10,
			children=[nav_text],
		)
		main_text = create_text_node('Main content here')
		main = create_element_node('main', backend_node_id=20, children=[main_text])

		body = create_element_node('body', backend_node_id=1, children=[nav, main])

		selector_map: DOMSelectorMap = {}
		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		content = result.to_structured_text()
		assert 'Main content here' in content
		# Navigation should be skipped
		assert 'Home | About | Contact' not in content

	def test_includes_navigation_when_enabled_no_main(self):
		"""Navigation should be included when include_navigation=True and no main content."""
		# When there's no main element, nav should be included if flag is set
		nav_text = create_text_node('Navigation Links')
		nav = create_element_node('nav', backend_node_id=10, children=[nav_text])
		div_text = create_text_node('Page content here')
		div = create_element_node('div', backend_node_id=20, children=[div_text])

		body = create_element_node('body', backend_node_id=1, children=[nav, div])

		selector_map: DOMSelectorMap = {}
		extractor = ContentExtractor(selector_map=selector_map, include_navigation=True)
		result = extractor.extract(body)  # type: ignore

		content = result.to_structured_text()
		assert 'Page content here' in content
		# Navigation should be included when no main content and flag is set
		assert 'Navigation Links' in content

	def test_finds_main_content_region(self):
		"""Should detect and prioritize main content region."""
		header_text = create_text_node('Site Header')
		header = create_element_node('header', backend_node_id=10, children=[header_text])

		main_text = create_text_node('Important content')
		main = create_element_node('main', backend_node_id=20, children=[main_text])

		footer_text = create_text_node('Site Footer')
		footer = create_element_node('footer', backend_node_id=30, children=[footer_text])

		body = create_element_node('body', backend_node_id=1, children=[header, main, footer])

		selector_map: DOMSelectorMap = {}
		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		assert result.main_content_found is True
		content = result.to_structured_text()
		assert 'Important content' in content

	def test_extracts_form_with_input_indices(self):
		"""Form inputs should include their indices for interaction."""
		label_text = create_text_node('Username:')
		label = create_element_node('label', backend_node_id=10, children=[label_text])

		input_elem = create_element_node(
			'input',
			backend_node_id=100,
			attributes={'type': 'text', 'name': 'username', 'placeholder': 'Enter username'},
		)

		form = create_element_node('form', backend_node_id=5, children=[label, input_elem])
		body = create_element_node('body', backend_node_id=1, children=[form])

		# Mark input as interactive
		selector_map: DOMSelectorMap = {100: input_elem}  # type: ignore

		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		content = result.to_structured_text()
		assert '[100]<input' in content
		assert 'username' in content.lower()

	def test_extracts_list_items(self):
		"""List items should be extracted with proper formatting."""
		li1_text = create_text_node('First item')
		li1 = create_element_node('li', backend_node_id=10, children=[li1_text])
		li2_text = create_text_node('Second item')
		li2 = create_element_node('li', backend_node_id=11, children=[li2_text])

		ul = create_element_node('ul', backend_node_id=5, children=[li1, li2])
		body = create_element_node('body', backend_node_id=1, children=[ul])

		selector_map: DOMSelectorMap = {}
		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		content = result.to_structured_text()
		assert 'First item' in content
		assert 'Second item' in content

	def test_extracts_table(self):
		"""Tables should be formatted as markdown tables."""
		th1 = create_element_node('th', backend_node_id=10, children=[create_text_node('Name')])
		th2 = create_element_node('th', backend_node_id=11, children=[create_text_node('Price')])
		header_row = create_element_node('tr', backend_node_id=5, children=[th1, th2])

		td1 = create_element_node('td', backend_node_id=20, children=[create_text_node('Widget')])
		td2 = create_element_node('td', backend_node_id=21, children=[create_text_node('$99')])
		data_row = create_element_node('tr', backend_node_id=6, children=[td1, td2])

		table = create_element_node('table', backend_node_id=1, children=[header_row, data_row])
		body = create_element_node('body', backend_node_id=0, children=[table])

		selector_map: DOMSelectorMap = {}
		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		content = result.to_structured_text()
		assert 'Name' in content
		assert 'Price' in content
		assert 'Widget' in content
		assert '$99' in content
		assert '|' in content  # Table separator

	def test_skips_script_and_style(self):
		"""Script and style tags should be completely skipped."""
		script = create_element_node(
			'script',
			backend_node_id=10,
			children=[create_text_node('alert("test")')],
		)
		style = create_element_node(
			'style',
			backend_node_id=11,
			children=[create_text_node('.foo { color: red; }')],
		)
		p = create_element_node('p', backend_node_id=12, children=[create_text_node('Visible content')])

		body = create_element_node('body', backend_node_id=1, children=[script, style, p])

		selector_map: DOMSelectorMap = {}
		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		content = result.to_structured_text()
		assert 'Visible content' in content
		assert 'alert' not in content
		assert 'color: red' not in content

	def test_result_stats(self):
		"""ExtractionResult should have accurate statistics."""
		text = create_text_node('Some text content')
		p = create_element_node('p', backend_node_id=10, children=[text])
		button = create_element_node(
			'button',
			backend_node_id=100,
			children=[create_text_node('Click')],
		)

		body = create_element_node('body', backend_node_id=1, children=[p, button])
		selector_map: DOMSelectorMap = {100: button}  # type: ignore

		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		assert result.total_interactive_elements == 1
		assert result.total_text_chars > 0
		assert result.extraction_method == 'structured_accessibility'

	def test_finds_main_by_aria_role(self):
		"""Should find main content via ARIA role attribute."""
		div_text = create_text_node('Main via role')
		div = create_element_node('div', backend_node_id=20, children=[div_text], role='main')

		body = create_element_node('body', backend_node_id=1, children=[div])

		selector_map: DOMSelectorMap = {}
		extractor = ContentExtractor(selector_map=selector_map)
		result = extractor.extract(body)  # type: ignore

		assert result.main_content_found is True
		content = result.to_structured_text()
		assert 'Main via role' in content


class TestExtractStructuredContent:
	"""Tests for the extract_structured_content convenience function."""

	def test_returns_content_and_stats(self):
		"""Should return tuple of content string and stats dict."""
		text = create_text_node('Hello world')
		p = create_element_node('p', backend_node_id=10, children=[text])
		body = create_element_node('body', backend_node_id=1, children=[p])

		selector_map: DOMSelectorMap = {}
		content, stats = extract_structured_content(body, selector_map)  # type: ignore

		assert isinstance(content, str)
		assert isinstance(stats, dict)
		assert 'Hello world' in content
		assert 'extraction_method' in stats

	def test_respects_max_chars(self):
		"""Should truncate content at max_chars limit."""
		# Create a lot of content
		paragraphs = []
		for i in range(100):
			text = create_text_node(f'Paragraph {i} with some content to fill space.')
			p = create_element_node('p', backend_node_id=10 + i, children=[text])
			paragraphs.append(p)

		body = create_element_node('body', backend_node_id=1, children=paragraphs)

		selector_map: DOMSelectorMap = {}
		content, stats = extract_structured_content(body, selector_map, max_chars=500)  # type: ignore

		assert len(content) <= 600  # Allow some overhead for truncation message


class TestExtractedSection:
	"""Tests for ExtractedSection dataclass."""

	def test_section_with_heading(self):
		"""Section with heading should format correctly."""
		section = ExtractedSection(
			role='main',
			heading='Page Title',
			content_lines=['Line 1', 'Line 2'],
		)

		result = ExtractionResult(
			sections=[section],
			total_text_chars=20,
			total_interactive_elements=0,
			main_content_found=True,
			extraction_method='test',
		)

		text = result.to_structured_text()
		assert '## Page Title' in text
		assert 'Line 1' in text
		assert 'Line 2' in text

	def test_section_with_role_only(self):
		"""Section without heading should show role."""
		section = ExtractedSection(
			role='form',
			heading=None,
			content_lines=['Form content'],
		)

		result = ExtractionResult(
			sections=[section],
			total_text_chars=12,
			total_interactive_elements=0,
			main_content_found=False,
			extraction_method='test',
		)

		text = result.to_structured_text()
		assert '[form]' in text
		assert 'Form content' in text

	def test_nested_subsections(self):
		"""Subsections should be indented."""
		child = ExtractedSection(
			role='article',
			heading='Article Title',
			content_lines=['Article content'],
		)

		parent = ExtractedSection(
			role='main',
			heading='Main Section',
			content_lines=['Main content'],
			subsections=[child],
		)

		result = ExtractionResult(
			sections=[parent],
			total_text_chars=30,
			total_interactive_elements=0,
			main_content_found=True,
			extraction_method='test',
		)

		text = result.to_structured_text()
		assert 'Main Section' in text
		assert 'Article Title' in text
		# Child should be indented (has more leading spaces)
		lines = text.split('\n')
		main_line = next((l for l in lines if 'Main Section' in l), '')
		article_line = next((l for l in lines if 'Article Title' in l), '')
		assert len(article_line) - len(article_line.lstrip()) > len(main_line) - len(main_line.lstrip())
