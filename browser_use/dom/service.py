import logging
from importlib import resources
from typing import Optional

from playwright.async_api import Page

from browser_use.dom.history_tree_processor.view import Coordinates
from browser_use.dom.views import (
	CoordinateSet,
	DOMBaseNode,
	DOMElementNode,
	DOMState,
	DOMTextNode,
	SelectorMap,
	ViewportInfo,
)

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


class DomService:
	def __init__(self, page: Page):
		self.page = page
		self.xpath_cache = {}
		# logger.debug("DomService initialized with page")

	# region - Clickable elements
	async def get_clickable_elements(
		self,
		highlight_elements: bool = True,
		focus_element: int = -1,
		viewport_expansion: int = 0,
	) -> DOMState:
		# logger.debug(f"Getting clickable elements. highlight={highlight_elements}, focus={focus_element}")
		element_tree = await self._build_dom_tree(highlight_elements, focus_element, viewport_expansion)
		# logger.debug(f"DOM tree built with {self._count_elements(element_tree)} nodes")
		selector_map = self._create_selector_map(element_tree)
		# logger.debug(f"Selector map created with {len(selector_map)} elements")

		return DOMState(element_tree=element_tree, selector_map=selector_map)

	def _count_elements(self, node: DOMBaseNode) -> int:
		"""Count elements for debugging"""
		if not isinstance(node, DOMElementNode):
			return 0
		return 1 + sum(self._count_elements(child) for child in node.children)

	async def _build_dom_tree(
		self,
		highlight_elements: bool,
		focus_element: int,
		viewport_expansion: int,
	) -> DOMElementNode:
		js_code = resources.read_text('browser_use.dom', 'buildDomTree.js')
		# logger.debug(f"Executing buildDomTree.js with highlight={highlight_elements}, focus={focus_element}")

		args = {
			'doHighlightElements': highlight_elements,
			'focusHighlightIndex': focus_element,
			'viewportExpansion': viewport_expansion,
		}

		eval_page = await self.page.evaluate(js_code, args)
		logger.debug(f"DOM tree data received, size: {len(str(eval_page))} characters")
		
		html_to_dict = self._parse_node(eval_page)

		if html_to_dict is None or not isinstance(html_to_dict, DOMElementNode):
			logger.error("Failed to parse HTML to dictionary")
			raise ValueError('Failed to parse HTML to dictionary')

		return html_to_dict

	def _create_selector_map(self, element_tree: DOMElementNode) -> SelectorMap:
		selector_map = {}

		def process_node(node: DOMBaseNode):
			if isinstance(node, DOMElementNode):
				if node.highlight_index is not None:
					selector_map[node.highlight_index] = node
					# logger.debug(f"Added to selector map: idx={node.highlight_index}, tag={node.tag_name}, xpath={node.xpath}")

				for child in node.children:
					process_node(child)

		process_node(element_tree)
		# logger.debug(f"Created selector map with {len(selector_map)} elements")
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
		
		# Log frame elements
		#if tag_name in ['iframe', 'frame', 'frameset']:
			# logger.debug(f"Processing {tag_name} element with xpath: {node_data.get('xpath')}")
		#	if 'frameContent' in node_data:
		#		logger.debug(f"Frame content: {node_data['frameContent']}")

		# Parse coordinates if they exist
		viewport_coordinates = None
		page_coordinates = None
		viewport_info = None

		if 'viewportCoordinates' in node_data:
			viewport_coordinates = CoordinateSet(
				top_left=Coordinates(**node_data['viewportCoordinates']['topLeft']),
				top_right=Coordinates(**node_data['viewportCoordinates']['topRight']),
				bottom_left=Coordinates(**node_data['viewportCoordinates']['bottomLeft']),
				bottom_right=Coordinates(**node_data['viewportCoordinates']['bottomRight']),
				center=Coordinates(**node_data['viewportCoordinates']['center']),
				width=node_data['viewportCoordinates']['width'],
				height=node_data['viewportCoordinates']['height'],
			)

		if 'pageCoordinates' in node_data:
			page_coordinates = CoordinateSet(
				top_left=Coordinates(**node_data['pageCoordinates']['topLeft']),
				top_right=Coordinates(**node_data['pageCoordinates']['topRight']),
				bottom_left=Coordinates(**node_data['pageCoordinates']['bottomLeft']),
				bottom_right=Coordinates(**node_data['pageCoordinates']['bottomRight']),
				center=Coordinates(**node_data['pageCoordinates']['center']),
				width=node_data['pageCoordinates']['width'],
				height=node_data['pageCoordinates']['height'],
			)

		if 'viewport' in node_data:
			viewport_info = ViewportInfo(
				scroll_x=node_data['viewport']['scrollX'],
				scroll_y=node_data['viewport']['scrollY'],
				width=node_data['viewport']['width'],
				height=node_data['viewport']['height'],
			)

		element_node = DOMElementNode(
			tag_name=tag_name,
			xpath=node_data['xpath'],
			attributes=node_data.get('attributes', {}),
			children=[],
			is_visible=node_data.get('isVisible', False),
			is_interactive=node_data.get('isInteractive', False),
			is_top_element=node_data.get('isTopElement', False),
			highlight_index=node_data.get('highlightIndex'),
			shadow_root=node_data.get('shadowRoot', False),
			parent=parent,
			frame_info=node_data.get('frameInfo'),
			is_frame_boundary=node_data.get('isFrameBoundary', False),
			viewport_coordinates=viewport_coordinates,
			page_coordinates=page_coordinates,
			viewport_info=viewport_info,
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
