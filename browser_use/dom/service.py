import logging
from importlib import resources
from typing import Optional

from playwright.async_api import Page

from browser_use.dom.views import (
	DOMBaseNode,
	DOMElementNode,
	DOMState,
	DOMTextNode,
	SelectorMap,
)

logger = logging.getLogger(__name__)


class DomService:
	def __init__(self, page: Page):
		self.page = page
		self.xpath_cache = {}

	# region - Clickable elements
	async def get_clickable_elements(self, highlight_elements: bool = True) -> DOMState:
		element_tree = await self._build_dom_tree(highlight_elements)
		selector_map = self._create_selector_map(element_tree)

		return DOMState(element_tree=element_tree, selector_map=selector_map)

	async def _build_dom_tree(self, highlight_elements: bool) -> DOMElementNode:
		js_code = resources.read_text('browser_use.dom', 'buildDomTree.js')

		eval_page = await self.page.evaluate(
			js_code, (highlight_elements)
		)  # This is quite big, so be careful
		html_to_dict = self._parse_node(eval_page)

		if html_to_dict is None or not isinstance(html_to_dict, DOMElementNode):
			raise ValueError('Failed to parse HTML to dictionary')

		return html_to_dict

	def _create_selector_map(self, element_tree: DOMElementNode) -> SelectorMap:
		selector_map = {}

		def process_node(node: DOMBaseNode):
			if isinstance(node, DOMElementNode):
				if node.highlight_index is not None:
					selector_map[node.highlight_index] = node

				for child in node.children:
					process_node(child)

		process_node(element_tree)
		return selector_map

	def _parse_node(
		self,
		node_data: dict,
		parent: Optional[DOMElementNode] = None,
	) -> Optional[DOMBaseNode]:
		if not node_data:
			return None

		if node_data.get('type') == 'TEXT_NODE':
			text_node = DOMTextNode(
				text=node_data['text'],
				is_visible=node_data['isVisible'],
				parent=parent,
			)

			return text_node

		tag_name = node_data['tagName']

		element_node = DOMElementNode(
			tag_name=tag_name,
			xpath=node_data['xpath'],
			attributes=node_data.get('attributes', {}),
			children=[],  # Initialize empty, will fill later
			is_visible=node_data.get('isVisible', False),
			is_interactive=node_data.get('isInteractive', False),
			is_top_element=node_data.get('isTopElement', False),
			highlight_index=node_data.get('highlightIndex'),
			shadow_root=node_data.get('shadowRoot', False),
			parent=parent,
		)

		children: list[DOMBaseNode] = []
		for child in node_data.get('children', []):
			if child is not None:
				child_node = self._parse_node(child, parent=element_node)
				if child_node is not None:
					children.append(child_node)

		element_node.children = children

		return element_node

	# endregion
