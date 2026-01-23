# @file purpose: Intelligent content filtering using accessibility tree and text density heuristics
"""
Content filtering module for intelligent extraction.

Uses ARIA roles, text density, and semantic signals to separate
main content from boilerplate (navigation, ads, footers).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.dom.views import EnhancedDOMTreeNode


class ContentRegion(Enum):
	"""Classification of page regions based on semantic role."""

	MAIN_CONTENT = 'main'  # Primary content area
	ARTICLE = 'article'  # Article/post content
	NAVIGATION = 'navigation'  # Nav menus, breadcrumbs
	BANNER = 'banner'  # Headers, site branding
	COMPLEMENTARY = 'complementary'  # Sidebars, related content
	CONTENTINFO = 'contentinfo'  # Footers
	FORM = 'form'  # Form regions
	SEARCH = 'search'  # Search boxes
	UNKNOWN = 'unknown'  # Unclassified


# ARIA roles that indicate main content regions
CONTENT_ROLES = frozenset({
	'main',
	'article',
	'region',
	'document',
	'application',
})

# ARIA roles that indicate boilerplate regions
BOILERPLATE_ROLES = frozenset({
	'navigation',
	'banner',
	'complementary',
	'contentinfo',
	'search',
	'directory',
	'menu',
	'menubar',
	'toolbar',
})

# HTML tags that map to content roles (implicit ARIA roles)
CONTENT_TAGS = frozenset({
	'main',
	'article',
	'section',
})

# HTML tags that map to boilerplate roles
BOILERPLATE_TAGS = frozenset({
	'nav',
	'header',
	'footer',
	'aside',
})

# Tags that should always be skipped in extraction
SKIP_TAGS = frozenset({
	'script',
	'style',
	'noscript',
	'svg',
	'path',
	'template',
	'slot',
})

# Data attributes that should be preserved (semantic identifiers)
SEMANTIC_DATA_ATTRS = frozenset({
	# Testing identifiers
	'data-testid',
	'data-test',
	'data-test-id',
	'data-cy',
	'data-selenium',
	'data-qa',
	'data-e2e',
	# Semantic markers
	'data-field-type',
	'data-field-name',
	'data-validation',
	'data-format',
	'data-type',
	'data-id',
	'data-name',
	'data-value',
	'data-label',
	# Form semantics
	'data-date-format',
	'data-mask',
	'data-inputmask',
	'data-datepicker',
	'data-required',
	'data-pattern',
	# State that might be useful
	'data-state',
	'data-selected',
	'data-active',
	'data-disabled',
	'data-expanded',
	# Content identifiers
	'data-product-id',
	'data-item-id',
	'data-article-id',
	'data-post-id',
	'data-user-id',
	'data-category',
	'data-price',
})


@dataclass
class ContentScore:
	"""Scoring for content vs boilerplate classification."""

	text_chars: int = 0
	link_chars: int = 0
	tag_count: int = 0
	paragraph_count: int = 0
	heading_count: int = 0
	list_item_count: int = 0
	form_element_count: int = 0
	aria_role: str | None = None
	implicit_role: str | None = None

	@property
	def text_density(self) -> float:
		"""Text density = text chars / tag count. Higher = more content-like."""
		if self.tag_count == 0:
			return 0.0
		return self.text_chars / self.tag_count

	@property
	def link_density(self) -> float:
		"""Link density = link chars / total text. Higher = more nav-like."""
		if self.text_chars == 0:
			return 0.0
		return self.link_chars / self.text_chars

	@property
	def is_likely_content(self) -> bool:
		"""Heuristic: high text density + low link density = content."""
		# ARIA role overrides heuristics
		if self.aria_role in CONTENT_ROLES:
			return True
		if self.aria_role in BOILERPLATE_ROLES:
			return False

		# Implicit role from HTML tag
		if self.implicit_role in CONTENT_ROLES:
			return True
		if self.implicit_role in BOILERPLATE_ROLES:
			return False

		# Text density heuristic (from Readability algorithm)
		# Content: high text density (>25 chars/tag), low link density (<0.3)
		return self.text_density > 25 and self.link_density < 0.3

	@property
	def is_likely_boilerplate(self) -> bool:
		"""Heuristic: low text density or high link density = boilerplate."""
		if self.aria_role in BOILERPLATE_ROLES:
			return True
		if self.implicit_role in BOILERPLATE_ROLES:
			return True

		# Navigation pattern: high link density
		if self.link_density > 0.5:
			return True

		# Sparse content pattern
		if self.text_density < 10 and self.link_density > 0.3:
			return True

		return False


@dataclass
class FilteredContent:
	"""Result of content filtering with metadata."""

	content: str
	stats: dict = field(default_factory=dict)
	removed_regions: list[str] = field(default_factory=list)
	main_content_found: bool = False


class ContentFilter:
	"""Filters DOM content using accessibility roles and text density."""

	def __init__(
		self,
		include_forms: bool = True,
		include_navigation: bool = False,
		include_complementary: bool = False,
	):
		"""Initialize content filter.

		Args:
			include_forms: Include form regions (useful for form filling tasks)
			include_navigation: Include navigation (useful for link extraction)
			include_complementary: Include sidebars (might have useful related content)
		"""
		self.include_forms = include_forms
		self.include_navigation = include_navigation
		self.include_complementary = include_complementary

	def classify_node(self, node: 'EnhancedDOMTreeNode') -> ContentRegion:
		"""Classify a DOM node into a content region type.

		Args:
			node: Enhanced DOM tree node with accessibility info

		Returns:
			ContentRegion classification
		"""
		# Check explicit ARIA role first
		if node.ax_node and node.ax_node.role:
			role = node.ax_node.role.lower()
			if role == 'main':
				return ContentRegion.MAIN_CONTENT
			elif role == 'article':
				return ContentRegion.ARTICLE
			elif role == 'navigation':
				return ContentRegion.NAVIGATION
			elif role == 'banner':
				return ContentRegion.BANNER
			elif role == 'complementary':
				return ContentRegion.COMPLEMENTARY
			elif role == 'contentinfo':
				return ContentRegion.CONTENTINFO
			elif role == 'form':
				return ContentRegion.FORM
			elif role == 'search':
				return ContentRegion.SEARCH

		# Check HTML tag for implicit role
		tag = node.tag_name.lower() if hasattr(node, 'tag_name') else node.node_name.lower()
		if tag == 'main':
			return ContentRegion.MAIN_CONTENT
		elif tag == 'article':
			return ContentRegion.ARTICLE
		elif tag == 'nav':
			return ContentRegion.NAVIGATION
		elif tag == 'header':
			return ContentRegion.BANNER
		elif tag == 'aside':
			return ContentRegion.COMPLEMENTARY
		elif tag == 'footer':
			return ContentRegion.CONTENTINFO
		elif tag == 'form':
			return ContentRegion.FORM

		# Check role attribute
		if node.attributes:
			role_attr = node.attributes.get('role', '').lower()
			if role_attr == 'main':
				return ContentRegion.MAIN_CONTENT
			elif role_attr == 'article':
				return ContentRegion.ARTICLE
			elif role_attr == 'navigation':
				return ContentRegion.NAVIGATION
			elif role_attr == 'banner':
				return ContentRegion.BANNER
			elif role_attr == 'complementary':
				return ContentRegion.COMPLEMENTARY
			elif role_attr == 'contentinfo':
				return ContentRegion.CONTENTINFO
			elif role_attr == 'search':
				return ContentRegion.SEARCH

		return ContentRegion.UNKNOWN

	def should_include_region(self, region: ContentRegion) -> bool:
		"""Determine if a region should be included in extraction.

		Args:
			region: ContentRegion classification

		Returns:
			True if region should be included
		"""
		# Always include main content and articles
		if region in (ContentRegion.MAIN_CONTENT, ContentRegion.ARTICLE, ContentRegion.UNKNOWN):
			return True

		# Conditional inclusion
		if region == ContentRegion.FORM and self.include_forms:
			return True
		if region == ContentRegion.NAVIGATION and self.include_navigation:
			return True
		if region == ContentRegion.COMPLEMENTARY and self.include_complementary:
			return True

		# Exclude boilerplate by default
		return False

	def score_subtree(self, node: 'EnhancedDOMTreeNode') -> ContentScore:
		"""Calculate content score for a DOM subtree.

		Args:
			node: Root of the subtree to score

		Returns:
			ContentScore with text/link density metrics
		"""
		score = ContentScore()

		# Get ARIA role
		if node.ax_node and node.ax_node.role:
			score.aria_role = node.ax_node.role.lower()

		# Get implicit role from tag
		tag = node.tag_name.lower() if hasattr(node, 'tag_name') else node.node_name.lower()
		if tag in CONTENT_TAGS:
			score.implicit_role = 'main'
		elif tag in BOILERPLATE_TAGS:
			score.implicit_role = 'navigation'

		# Recursively collect metrics
		self._collect_metrics(node, score, in_link=False)

		return score

	def _collect_metrics(
		self,
		node: 'EnhancedDOMTreeNode',
		score: ContentScore,
		in_link: bool,
	) -> None:
		"""Recursively collect text density metrics.

		Args:
			node: Current node
			score: Score object to update
			in_link: Whether we're inside an anchor tag
		"""
		from browser_use.dom.views import NodeType

		tag = node.node_name.lower() if node.node_name else ''

		# Skip non-content tags
		if tag in SKIP_TAGS:
			return

		# Track tag count
		if node.node_type == NodeType.ELEMENT_NODE:
			score.tag_count += 1

			# Track specific element types
			if tag == 'p':
				score.paragraph_count += 1
			elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
				score.heading_count += 1
			elif tag == 'li':
				score.list_item_count += 1
			elif tag in ('input', 'select', 'textarea', 'button'):
				score.form_element_count += 1

		# Track text content
		if node.node_type == NodeType.TEXT_NODE and node.node_value:
			text_len = len(node.node_value.strip())
			score.text_chars += text_len
			if in_link:
				score.link_chars += text_len

		# Check if entering a link
		is_link = tag == 'a'

		# Process children
		for child in node.children:
			self._collect_metrics(child, score, in_link=in_link or is_link)


def is_semantic_data_attr(attr_name: str) -> bool:
	"""Check if a data-* attribute should be preserved.

	Args:
		attr_name: Attribute name (e.g., 'data-testid')

	Returns:
		True if attribute should be kept in extraction
	"""
	if not attr_name.startswith('data-'):
		return True  # Not a data attribute, keep it

	# Check against whitelist first
	if attr_name in SEMANTIC_DATA_ATTRS:
		return True

	# Get the part after 'data-'
	suffix = attr_name[5:].lower()  # Remove 'data-' prefix

	# Reject known framework internal attributes
	framework_patterns = (
		'reactid',  # React internal
		'react-',  # React internal
		'v-',  # Vue internal (data-v-abc123)
		'ng-',  # Angular internal
		'ember-',  # Ember internal
		'svelte-',  # Svelte internal
		'styled-',  # styled-components
		'emotion-',  # Emotion CSS
	)
	if any(suffix.startswith(p) or suffix == p.rstrip('-') for p in framework_patterns):
		return False

	# Testing identifiers (various naming conventions)
	test_patterns = ('test', 'qa', 'e2e', 'selenium', 'cy-', 'cypress')
	if any(p in suffix for p in test_patterns):
		return True

	# Semantic identifier patterns - must be word boundaries, not substrings
	# e.g., data-product-id, data-user-id, but not data-reactid
	semantic_suffixes = (
		'-id', '-name', '-type', '-value', '-label',  # Must be at end
		'id-', 'name-', 'type-', 'value-', 'label-',  # Must be at start of compound
	)
	if any(suffix.endswith(s.lstrip('-')) or suffix.startswith(s.rstrip('-')) for s in semantic_suffixes):
		return True

	# Check for exact matches of semantic words
	semantic_exact = ('id', 'name', 'type', 'value', 'label')
	if suffix in semantic_exact:
		return True

	# Form-related patterns
	form_patterns = ('field', 'input', 'form', 'validation', 'format', 'mask', 'pattern')
	if any(p in suffix for p in form_patterns):
		return True

	return False


def is_spa_state_json(text: str) -> bool:
	"""Detect if text looks like SPA framework state/config JSON.

	Args:
		text: Text content to check

	Returns:
		True if text appears to be framework state rather than content
	"""
	if not text or len(text) < 50:
		return False

	stripped = text.strip()

	# Must start like JSON
	if not (stripped.startswith('{') or stripped.startswith('[')):
		return False

	# Framework state indicators
	framework_patterns = [
		'"$type"',  # C#/.NET serialization
		'"__typename"',  # GraphQL
		'"$$typeof"',  # React
		'"_reactRootContainer"',  # React
		'"__NEXT_DATA__"',  # Next.js
		'"__NUXT__"',  # Nuxt.js
		'"props":{',  # React props
		'"state":{',  # Redux/Vuex state
		'"mutations"',  # Vuex mutations
		'"reducers"',  # Redux reducers
		'window.__',  # Global state injection
		'"hydrate"',  # SSR hydration
		'"preloadedState"',  # Redux
		'"initialState"',  # Generic state
		'"pageProps"',  # Next.js
	]

	for pattern in framework_patterns:
		if pattern in text:
			return True

	# High ratio of special characters to letters suggests encoded data
	letters = sum(1 for c in text if c.isalpha())
	special = sum(1 for c in text if c in '{}[]":,\\')
	if letters > 0 and special / letters > 2:
		return True

	return False


def find_main_content_root(node: 'EnhancedDOMTreeNode') -> 'EnhancedDOMTreeNode | None':
	"""Find the main content root in a DOM tree using accessibility roles.

	Searches for <main> element, role="main", or article regions.

	Args:
		node: Root of DOM tree to search

	Returns:
		The main content node if found, None otherwise
	"""
	from browser_use.dom.views import NodeType

	if node.node_type != NodeType.ELEMENT_NODE:
		# Check children of non-element nodes (document nodes)
		for child in node.children:
			result = find_main_content_root(child)
			if result:
				return result
		return None

	# Check if this node is main content
	tag = node.tag_name.lower() if hasattr(node, 'tag_name') else node.node_name.lower()

	# Check explicit role attribute
	role = None
	if node.attributes:
		role = node.attributes.get('role', '').lower()

	# Check accessibility role
	ax_role = None
	if node.ax_node and node.ax_node.role:
		ax_role = node.ax_node.role.lower()

	# Main content detection
	if tag == 'main' or role == 'main' or ax_role == 'main':
		return node

	# Article as fallback
	if tag == 'article' or role == 'article' or ax_role == 'article':
		return node

	# Recurse into children
	for child in node.children:
		result = find_main_content_root(child)
		if result:
			return result

	# Also check shadow roots
	if node.shadow_roots:
		for shadow_root in node.shadow_roots:
			result = find_main_content_root(shadow_root)
			if result:
				return result

	return None
