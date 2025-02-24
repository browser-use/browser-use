import gc
import json
import logging
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
	from playwright.async_api import Page

from browser_use.dom.views import (
	DOMBaseNode,
	DOMElementNode,
	DOMState,
	DOMTextNode,
	SelectorMap,
)
from browser_use.utils import time_execution_async

logger = logging.getLogger(__name__)


@dataclass
class ViewportInfo:
	width: int
	height: int


class DomService:
	def __init__(self, page: 'Page'):
		self.page = page
		self.xpath_cache = {}

		# self.js_code = resources.read_text('browser_use.dom', 'buildDomTree.js')
		self.js_code = resources.read_text('browser_use.dom', 'buildMultionDomTree.js')
	# region - Clickable elements
	@time_execution_async('--get_clickable_elements')
	async def get_clickable_elements(
		self,
		highlight_elements: bool = True,
		focus_element: int = -1,
		viewport_expansion: int = 0,
	) -> DOMState:
		element_tree, selector_map = await self._build_dom_tree(highlight_elements, focus_element, viewport_expansion)
		print("element_tree", element_tree)
		return DOMState(element_tree=element_tree, selector_map=selector_map)

	@time_execution_async('--build_dom_tree')
	async def _build_dom_tree(
		self,
		highlight_elements: bool,
		focus_element: int,
		viewport_expansion: int,
	) -> tuple[DOMElementNode, SelectorMap]:
		if await self.page.evaluate('1+1') != 2:
			raise ValueError('The page cannot evaluate javascript code properly')

		# NOTE: We execute JS code in the browser to extract important DOM information.
		#       The returned hash map contains information about the DOM tree and the
		#       relationship between the DOM elements.
		debug_mode = logger.getEffectiveLevel() == logging.DEBUG
		args = {
			'doHighlightElements': highlight_elements,
			'focusHighlightIndex': focus_element,
			'viewportExpansion': viewport_expansion,
			'debugMode': debug_mode,
		}

		try:
			eval_page = await self.page.evaluate(self.js_code, args)
		except Exception as e:
			logger.error('Error evaluating JavaScript: %s', e)
			raise

		# Only log performance metrics in debug mode
		if debug_mode and 'perfMetrics' in eval_page:
			logger.debug('DOM Tree Building Performance Metrics:\n%s', json.dumps(eval_page['perfMetrics'], indent=2))

		return await self._construct_dom_tree(eval_page)

	@time_execution_async('--construct_dom_tree')
	async def _construct_dom_tree(
		self,
		eval_page: dict,
	) -> tuple[DOMElementNode, SelectorMap]:
		try:
			js_node_map = eval_page['map']
			js_root_id = eval_page['rootId']
		except KeyError as e:
			raise ValueError(f"Missing required key in eval_page: {e}")

		selector_map = {}
		node_map = {}

		for id, node_data in js_node_map.items():
			try:
				node, children_ids = self._parse_node(node_data)
				if node is None:
					continue

				node_map[str(id)] = node

				if isinstance(node, DOMElementNode) and node.highlight_index is not None:
					selector_map[node.highlight_index] = node

				if isinstance(node, DOMElementNode):
					for child_id in children_ids:
						if str(child_id) not in node_map:
							continue

						child_node = node_map[str(child_id)]

						child_node.parent = node
						node.children.append(child_node)
			except Exception as e:
				logger.error(f"Error processing node {id}: {e}")
				raise

		try:
			html_to_dict = node_map[str(js_root_id)]
		except KeyError:
			raise ValueError(f"Root node with id {js_root_id} not found in node map")

		del node_map
		del js_node_map
		del js_root_id

		gc.collect()

		if html_to_dict is None or not isinstance(html_to_dict, DOMElementNode):
			raise ValueError('Failed to parse HTML to dictionary')

		logger.debug(f"Constructed DOM tree with {len(selector_map)} interactive elements")
		return html_to_dict, selector_map
	def _parse_node(
		self,
		node_data: dict,
	) -> tuple[Optional[DOMBaseNode], list[str]]:
		try:
			if not node_data:
				return None, []

			# Process text nodes immediately
			if node_data.get('type') == 'TEXT_NODE':
				text_node = DOMTextNode(
					text=node_data['text'],
					is_visible=node_data['isVisible'],
					parent=None,
				)
				return text_node, []

			# Process coordinates if they exist for element nodes
			viewport_info = None

			if 'viewport' in node_data:
				viewport_info = ViewportInfo(
					width=node_data['viewport']['width'],
					height=node_data['viewport']['height'],
				)

			# Convert attributes to a hashable type (tuple of key-value pairs)
			attributes = {}
			for key, value in node_data.get('attributes', {}).items():
				if isinstance(value, (str, int, float, bool, type(None))):
					attributes[key] = value
				else:
					attributes[key] = str(value)  # Convert non-hashable types to strings

			element_node = DOMElementNode(
				tag_name=node_data['tagName'],
				xpath=node_data['xpath'],
				attributes=attributes,
				children=[],
				is_visible=node_data.get('isVisible', False),
				is_interactive=node_data.get('isInteractive', False),
				is_top_element=node_data.get('isTopElement', False),
				is_in_viewport=node_data.get('isInViewport', False),
				highlight_index=node_data.get('highlightIndex'),
				shadow_root=node_data.get('shadowRoot', False),
				parent=None,
				viewport_info=viewport_info,
			)

			children_ids = [str(child_id) for child_id in node_data.get('children', [])]

			return element_node, children_ids

		except Exception as e:
			logger.error(f"Error parsing node: {e}")
			raise
