import logging
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING
from urllib.parse import urlparse

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

		self.js_code = resources.files('browser_use.dom').joinpath('buildDomTree.js').read_text()

	# region - Clickable elements
	@time_execution_async('--get_clickable_elements')
	async def get_clickable_elements(
		self,
		highlight_elements: bool = True,
		focus_element: int = -1,
		viewport_expansion: int = 0,
	) -> DOMState:
		element_tree, selector_map = await self._build_dom_tree(highlight_elements, focus_element, viewport_expansion)
		return DOMState(element_tree=element_tree, selector_map=selector_map)

	@time_execution_async('--get_cross_origin_iframes')
	async def get_cross_origin_iframes(self) -> list[str]:
		# invisible cross-origin iframes are used for ads and tracking, dont open those
		hidden_frame_urls = await self.page.locator('iframe').filter(visible=False).evaluate_all('e => e.map(e => e.src)')

		is_ad_url = lambda url: any(
			domain in urlparse(url).netloc for domain in ('doubleclick.net', 'adroll.com', 'googletagmanager.com')
		)

		return [
			frame.url
			for frame in self.page.frames
			if urlparse(frame.url).netloc  # exclude data:urls and about:blank
			and urlparse(frame.url).netloc != urlparse(self.page.url).netloc  # exclude same-origin iframes
			and frame.url not in hidden_frame_urls  # exclude hidden frames
			and not is_ad_url(frame.url)  # exclude most common ad network tracker frame URLs
		]

	@time_execution_async('--build_dom_tree')
	async def _build_dom_tree(
		self,
		highlight_elements: bool,
		focus_element: int,
		viewport_expansion: int,
	) -> tuple[DOMElementNode, SelectorMap]:
		if await self.page.evaluate('1+1') != 2:
			raise ValueError('The page cannot evaluate javascript code properly')

		if self.page.url == 'about:blank':
			# short-circuit if the page is a new empty tab for speed, no need to inject buildDomTree.js
			return (
				DOMElementNode(
					tag_name='body',
					xpath='',
					attributes={},
					children=[],
					is_visible=False,
					parent=None,
				),
				{},
			)

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
			eval_page: dict = await self.page.evaluate(self.js_code, args)
		except Exception as e:
			logger.error('Error evaluating JavaScript: %s', e)
			raise

		# Only log performance metrics in debug mode
		if debug_mode and 'perfMetrics' in eval_page:
			perf = eval_page['perfMetrics']

			# Get key metrics for summary
			total_nodes = perf.get('nodeMetrics', {}).get('totalNodes', 0)
			# processed_nodes = perf.get('nodeMetrics', {}).get('processedNodes', 0)

			# Count interactive elements from the DOM map
			interactive_count = 0
			if 'map' in eval_page:
				for node_data in eval_page['map'].values():
					if isinstance(node_data, dict) and node_data.get('isInteractive'):
						interactive_count += 1

			# Create concise summary
			url_short = self.page.url[:50] + '...' if len(self.page.url) > 50 else self.page.url
			logger.debug(
				'🔎 Ran buildDOMTree.js interactive element detection on: %s interactive=%d/%d',
				url_short,
				interactive_count,
				total_nodes,
				# processed_nodes,
			)

		return await self._construct_dom_tree(eval_page)

	@time_execution_async('--construct_dom_tree')
	async def _construct_dom_tree(
		self,
		eval_page: dict,
	) -> tuple[DOMElementNode, SelectorMap]:
		js_node_map = eval_page['map']
		js_root_id = eval_page['rootId']

		selector_map = {}
		node_map = {}

		for id, node_data in js_node_map.items():
			node, children_ids = self._parse_node(node_data)
			if node is None:
				continue

			node_map[id] = node

			if isinstance(node, DOMElementNode) and node.highlight_index is not None:
				selector_map[node.highlight_index] = node

			# NOTE: We know that we are building the tree bottom up
			#       and all children are already processed.
			if isinstance(node, DOMElementNode):
				for child_id in children_ids:
					if child_id not in node_map:
						continue

					child_node = node_map[child_id]

					child_node.parent = node
					node.children.append(child_node)

		html_to_dict = node_map[str(js_root_id)]

		del node_map
		del js_node_map
		del js_root_id

		if html_to_dict is None or not isinstance(html_to_dict, DOMElementNode):
			raise ValueError('Failed to parse HTML to dictionary')

		return html_to_dict, selector_map

	def _parse_node(
		self,
		node_data: dict,
	) -> tuple[DOMBaseNode | None, list[int]]:
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

		element_node = DOMElementNode(
			tag_name=node_data['tagName'],
			xpath=node_data['xpath'],
			attributes=node_data.get('attributes', {}),
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

		children_ids = node_data.get('children', [])

		return element_node, children_ids
