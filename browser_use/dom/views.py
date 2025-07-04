from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Optional

from browser_use.dom.history_tree_processor.view import CoordinateSet, HashedDomElement, ViewportInfo
from browser_use.dom.utils import cap_text_length
from browser_use.utils import time_execution_sync

# Avoid circular import issues
if TYPE_CHECKING:
	from .views import DOMElementNode


@dataclass(frozen=False)
class DOMBaseNode:
	is_visible: bool
	# Use None as default and set parent later to avoid circular reference issues
	parent: Optional['DOMElementNode']

	def __json__(self) -> dict:
		raise NotImplementedError('DOMBaseNode is an abstract class')


@dataclass(frozen=False)
class DOMTextNode(DOMBaseNode):
	text: str
	type: str = 'TEXT_NODE'

	def has_parent_with_highlight_index(self) -> bool:
		current = self.parent
		while current is not None:
			# stop if the element has a highlight index (will be handled separately)
			if current.highlight_index is not None:
				return True

			current = current.parent
		return False

	def is_parent_in_viewport(self) -> bool:
		if self.parent is None:
			return False
		return self.parent.is_in_viewport

	def is_parent_top_element(self) -> bool:
		if self.parent is None:
			return False
		return self.parent.is_top_element

	def __json__(self) -> dict:
		return {
			'text': self.text,
			'type': self.type,
		}


DEFAULT_INCLUDE_ATTRIBUTES = [
	'title',
	'type',
	'checked',
	'name',
	'role',
	'value',
	'placeholder',
	'data-date-format',
	'alt',
	'aria-label',
	'aria-expanded',
	'data-state',
	'aria-checked',
]


@dataclass(frozen=False)
class DOMElementNode(DOMBaseNode):
	"""
	xpath: the xpath of the element from the last root node (shadow root or iframe OR document if no shadow root or iframe).
	To properly reference the element we need to recursively switch the root node until we find the element (work you way up the tree with `.parent`)
	"""

	tag_name: str
	xpath: str
	attributes: dict[str, str]
	children: list[DOMBaseNode]
	is_interactive: bool = False
	is_top_element: bool = False
	is_in_viewport: bool = False
	shadow_root: bool = False
	highlight_index: int | None = None
	viewport_coordinates: CoordinateSet | None = None
	page_coordinates: CoordinateSet | None = None
	viewport_info: ViewportInfo | None = None

	"""
	### State injected by the browser context.

	The idea is that the clickable elements are sometimes persistent from the previous page -> tells the model which objects are new/_how_ the state has changed
	"""
	is_new: bool | None = None

	def __json__(self) -> dict:
		return {
			'tag_name': self.tag_name,
			'xpath': self.xpath,
			'attributes': self.attributes,
			'is_visible': self.is_visible,
			'is_interactive': self.is_interactive,
			'is_top_element': self.is_top_element,
			'is_in_viewport': self.is_in_viewport,
			'shadow_root': self.shadow_root,
			'highlight_index': self.highlight_index,
			'viewport_coordinates': self.viewport_coordinates,
			'page_coordinates': self.page_coordinates,
			'children': [child.__json__() for child in self.children],
		}

	def __repr__(self) -> str:
		tag_str = f'<{self.tag_name}'

		# Add attributes
		for key, value in self.attributes.items():
			tag_str += f' {key}="{value}"'
		tag_str += '>'

		# Add extra info
		extras = []
		if self.is_interactive:
			extras.append('interactive')
		if self.is_top_element:
			extras.append('top')
		if self.shadow_root:
			extras.append('shadow-root')
		if self.highlight_index is not None:
			extras.append(f'highlight:{self.highlight_index}')
		if self.is_in_viewport:
			extras.append('in-viewport')

		if extras:
			tag_str += f' [{", ".join(extras)}]'

		return tag_str

	@cached_property
	def hash(self) -> HashedDomElement:
		from browser_use.dom.history_tree_processor.service import (
			HistoryTreeProcessor,
		)

		return HistoryTreeProcessor._hash_dom_element(self)

	def get_all_text_till_next_clickable_element(self, max_depth: int = -1) -> str:
		text_parts = []

		def collect_text(node: DOMBaseNode, current_depth: int) -> None:
			if max_depth != -1 and current_depth > max_depth:
				return

			# Skip this branch if we hit a highlighted element (except for the current node)
			if isinstance(node, DOMElementNode) and node != self and node.highlight_index is not None:
				return

			if isinstance(node, DOMTextNode):
				text_parts.append(node.text)
			elif isinstance(node, DOMElementNode):
				for child in node.children:
					collect_text(child, current_depth + 1)

		collect_text(self, 0)
		return '\n'.join(text_parts).strip()

	@time_execution_sync('--clickable_elements_to_string')
	def clickable_elements_to_string(self, include_attributes: list[str] | None = None) -> str:
		"""Convert the processed DOM content to HTML."""
		formatted_text = []

		if not include_attributes:
			include_attributes = DEFAULT_INCLUDE_ATTRIBUTES

		def process_node(node: DOMBaseNode, depth: int) -> None:
			next_depth = int(depth)
			depth_str = depth * '\t'

			if isinstance(node, DOMElementNode):
				# Add element with highlight_index
				if node.highlight_index is not None:
					next_depth += 1

					text = node.get_all_text_till_next_clickable_element()
					attributes_html_str = None
					if include_attributes:
						attributes_to_include = {
							key: str(value).strip()
							for key, value in node.attributes.items()
							if key in include_attributes and str(value).strip() != ''
						}

						# If value of any of the attributes is the same as ANY other value attribute only include the one that appears first in include_attributes
						# WARNING: heavy vibes, but it seems good enough for saving tokens (it kicks in hard when it's long text)

						# Pre-compute ordered keys that exist in both lists (faster than repeated lookups)
						ordered_keys = [key for key in include_attributes if key in attributes_to_include]

						if len(ordered_keys) > 1:  # Only process if we have multiple attributes
							keys_to_remove = set()  # Use set for O(1) lookups
							seen_values = {}  # value -> first_key_with_this_value

							for key in ordered_keys:
								value = attributes_to_include[key]
								if len(value) > 5:  # to not remove false, true, etc
									if value in seen_values:
										# This value was already seen with an earlier key, so remove this key
										keys_to_remove.add(key)
									else:
										# First time seeing this value, record it
										seen_values[value] = key

							# Remove duplicate keys (no need to check existence since we know they exist)
							for key in keys_to_remove:
								del attributes_to_include[key]

						# Easy LLM optimizations
						# if tag == role attribute, don't include it
						if node.tag_name == attributes_to_include.get('role'):
							del attributes_to_include['role']

						# Remove attributes that duplicate the node's text content
						attrs_to_remove_if_text_matches = ['aria-label', 'placeholder', 'title']
						for attr in attrs_to_remove_if_text_matches:
							if (
								attributes_to_include.get(attr)
								and attributes_to_include.get(attr, '').strip().lower() == text.strip().lower()
							):
								del attributes_to_include[attr]

						if attributes_to_include.items():
							# Format as key1='value1' key2='value2'
							attributes_html_str = ' '.join(
								f'{key}={cap_text_length(value, 15)}' for key, value in attributes_to_include.items()
							)

					# Build the line
					if node.is_new:
						highlight_indicator = f'*[{node.highlight_index}]'

					else:
						highlight_indicator = f'[{node.highlight_index}]'

					line = f'{depth_str}{highlight_indicator}<{node.tag_name}'

					if attributes_html_str:
						line += f' {attributes_html_str}'

					if text:
						# Add space before >text only if there were NO attributes added before
						text = text.strip()
						if not attributes_html_str:
							line += ' '
						line += f'>{text}'

					# Add space before /> only if neither attributes NOR text were added
					elif not attributes_html_str:
						line += ' '

					# makes sense to have if the website has lots of text -> so the LLM knows which things are part of the same clickable element and which are not
					line += ' />'  # 1 token
					formatted_text.append(line)

				# Process children regardless
				for child in node.children:
					process_node(child, next_depth)

			elif isinstance(node, DOMTextNode):
				# Add text only if it doesn't have a highlighted parent
				if node.has_parent_with_highlight_index():
					return

				if node.parent and node.parent.is_visible and node.parent.is_top_element:
					formatted_text.append(f'{depth_str}{node.text}')

		process_node(self, 0)
		return '\n'.join(formatted_text)


SelectorMap = dict[int, DOMElementNode]


@dataclass
class DOMState:
	element_tree: DOMElementNode
	selector_map: SelectorMap
