import logging
from importlib import resources
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
	from browser_use.browser.types import Page

from dataclasses import dataclass

from browser_use.dom.views import (
	DOMBaseNode,
	DOMElementNode,
	DOMState,
	DOMTextNode,
	SelectorMap,
	ViewportInfo,
)
from browser_use.utils import time_execution_async

# @dataclass
# class ViewportInfo:
# 	width: int
# 	height: int


@dataclass
class PageFrameEvaluationResult:
	url: str
	result: dict
	name: str | None = None
	id: str | None = None

	@property
	def known_frame_urls(self) -> list[str]:
		return [
			v.get('attributes', {}).get('src')
			for v in self.map.values()
			if v.get('hasIframeContent') and v.get('attributes', {}).get('src')
		]

	@property
	def map(self) -> dict:
		return self.result.get('map', {})

	@property
	def map_size(self) -> int:
		return len(self.map)

	@property
	def perf_metrics(self) -> dict:
		return self.result.get('perfMetrics', {})

	@property
	def short_url(self) -> str:
		return self.url[:50] + '...' if len(self.url) > 50 else self.url

	@property
	def root_id(self) -> str | None:
		return self.result.get('rootId')


class DomService:
	logger: logging.Logger

	def __init__(self, page: 'Page', logger: logging.Logger | None = None):
		self.page = page
		self.xpath_cache = {}
		self.logger = logger or logging.getLogger(__name__)

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
		debug_mode = self.logger.getEffectiveLevel() == logging.DEBUG
		args = {
			'doHighlightElements': highlight_elements,
			'focusHighlightIndex': focus_element,
			'viewportExpansion': viewport_expansion,
			'debugMode': debug_mode,
			'initialIndex': 0,
		}

		try:
			eval_page: dict = await self.page.evaluate(self.js_code, args)
			page_eval_result = PageFrameEvaluationResult(
				url=self.page.url,
				result=eval_page,
			)
		except Exception as e:
			self.logger.error('Error evaluating JavaScript: %s', e)
			raise

		frames = [page_eval_result]
		total_map_size = page_eval_result.map_size

		known_frame_urls = page_eval_result.known_frame_urls
		# TODO: only look in iframes from enabled_domains
		for iframe in self.page.frames:
			if (
				iframe.url
				and iframe.url != self.page.url
				and not iframe.url.startswith('data:')
				and iframe.url not in known_frame_urls
			):
				try:
					frame_element = await iframe.frame_element()
				except Exception as e:
					self.logger.error('Error getting frame element for iframe %s: %s', iframe.url, e)
					continue

				if not await frame_element.is_visible():
					continue

				args['initialIndex'] = total_map_size  # continue indexing from the last index
				try:
					name = await frame_element.get_attribute('name')
					id = await frame_element.get_attribute('id')
					iframe_eval_result = await iframe.evaluate(self.js_code, args)
					frame = PageFrameEvaluationResult(
						url=iframe.url,
						result=iframe_eval_result,
						name=name,
						id=id,
					)
					frames.append(frame)
					known_frame_urls.append(iframe.url)
					known_frame_urls.extend(frame.known_frame_urls)
					total_map_size += frame.map_size
				except Exception as e:
					self.logger.error('Error evaluating JavaScript in iframe %s: %s', iframe.url, e)
					continue

		# Only log performance metrics in debug mode
		if debug_mode and len(frames) > 1:
			for index, frame in enumerate(frames):
				perf = frame.perf_metrics
				if perf:
					# Get key metrics for summary
					total_nodes = perf.get('nodeMetrics', {}).get('totalNodes', 0)
					# processed_nodes = perf.get('nodeMetrics', {}).get('processedNodes', 0)

					# Count interactive elements from the DOM map
					interactive_count = 0
					for node_data in frame.map.values():
						if isinstance(node_data, dict) and node_data.get('isInteractive'):
							interactive_count += 1

					# Create concise summary
					self.logger.debug(
						f'🔎 Ran buildDOMTree.js interactive element detection on{" iframe" if index > 0 else ""}: %s interactive=%d/%d\n',
						frame.short_url,
						interactive_count,
						total_nodes,
						# processed_nodes,
					)

		return await self._construct_dom_tree(frames)

	@time_execution_async('--construct_dom_tree')
	async def _construct_dom_tree(
		self,
		frames: list[PageFrameEvaluationResult],
	) -> tuple[DOMElementNode, SelectorMap]:
		# The first page in eval_pages is the main page, and it contains the rootId
		js_root_id = frames[0].root_id
		if js_root_id is None:
			raise ValueError('No rootId found in the evaluated page structure')

		selector_map: SelectorMap = {}
		node_map: dict[str, DOMBaseNode] = {}

		for frame in frames:
			js_node_map = frame.map
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

		# For each child iframe, we need to set the parent of the root element to the iframe element.
		for frame in frames[1:]:
			content_root_node = node_map.get(frame.root_id)
			if content_root_node:
				# Find the iframe element in the main page
				iframe_element_node = next(
					(
						node
						for node in node_map.values()
						if isinstance(node, DOMElementNode)
						and node.is_iframe_element(url=frame.url, name=frame.name, id=frame.id)
					),
					None,
				)
				if iframe_element_node:
					if not iframe_element_node.children:
						iframe_element_node.children = [content_root_node]
						content_root_node.parent = iframe_element_node
						continue
					else:
						self.logger.warning(
							'Iframe element %s already has children, skipping',
							frame.short_url,
						)
				else:
					self.logger.warning(
						'Could not find iframe element for %s in the main page DOM',
						frame.short_url,
					)

			# If we could not find the iframe element, remove the frame's nodes from the maps.
			for id in frame.map.keys():
				node = node_map.get(id)
				# Remove the node from the selector map if it has a highlight index
				if isinstance(node, DOMElementNode) and node.highlight_index is not None and node.highlight_index in selector_map:
					del selector_map[node.highlight_index]

				del node_map[id]

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
