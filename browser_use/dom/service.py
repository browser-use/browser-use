import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from cdp_use.cdp.accessibility.commands import GetFullAXTreeReturns
from cdp_use.cdp.accessibility.types import AXNode
from cdp_use.cdp.dom.commands import GetDocumentReturns
from cdp_use.cdp.dom.types import Node
from cdp_use.cdp.domsnapshot.commands import CaptureSnapshotReturns

from browser_use.dom.enhanced_snapshot import (
	REQUIRED_COMPUTED_STYLES,
	build_snapshot_lookup,
)
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import (
	EnhancedAXNode,
	EnhancedAXProperty,
	EnhancedDOMTreeNode,
	NodeType,
	SerializedDOMState,
)
from browser_use.observability import observe_debug
from browser_use.utils import time_execution_async, time_execution_sync

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession

logger = logging.getLogger(__name__)


class DomService:
	"""
	Service for getting the DOM tree and other DOM-related information.

	Either browser or page must be provided.
	"""

	def __init__(self, browser: 'BrowserSession'):
		self.browser = browser

		self.session_id_initialized_domains_cache: dict[str, bool] = {}

	async def _get_current_page_session_id(self) -> str:
		"""Get the target ID for a playwright page.

		TODO: this is a REALLY hacky way -> if multiple same urls are open then this will break
		"""
		cdp_client = await self.browser.get_cdp_client()
		session_id = await self.browser.get_current_page_cdp_session_id()

		if session_id in self.session_id_initialized_domains_cache:
			return session_id

		start_auto_attach = time.time()
		await cdp_client.send.Target.setAutoAttach(params={'autoAttach': True, 'waitForDebuggerOnStart': False, 'flatten': True})
		end_auto_attach = time.time()
		logger.debug(f'⏱️ Target.setAutoAttach() took {end_auto_attach - start_auto_attach:.3f} seconds')

		# Time the enable calls
		start_enables = time.time()
		await cdp_client.send.DOM.enable(session_id=session_id)
		await cdp_client.send.Accessibility.enable(session_id=session_id)
		await cdp_client.send.DOMSnapshot.enable(session_id=session_id)
		await cdp_client.send.Page.enable(session_id=session_id)
		end_enables = time.time()
		logger.debug(f'⏱️ CDP domain enables took {end_enables - start_enables:.3f} seconds')

		self.session_id_initialized_domains_cache[session_id] = True

		return session_id

	def _extract_ax_property_value(self, value) -> str | bool | None:
		"""Extract value from various formats returned by the accessibility API."""
		if isinstance(value, dict):
			extracted = value.get('value', value)
			if isinstance(extracted, (str, bool)) or extracted is None:
				return extracted
			return str(extracted)  # Convert to string if not expected type
		elif isinstance(value, list) and len(value) > 0:
			# Sometimes values are returned as a list with one element
			return self._extract_ax_property_value(value[0])
		elif isinstance(value, (str, bool)) or value is None:
			return value
		else:
			return str(value) if value is not None else None

	def _build_enhanced_ax_node(self, ax_node: AXNode) -> EnhancedAXNode:
		"""Build enhanced accessibility node from CDP AX node."""

		properties = None
		if 'properties' in ax_node and ax_node['properties']:
			properties = []
			for prop in ax_node['properties']:
				try:
					prop_name = prop.get('name')
					prop_value = self._extract_ax_property_value(prop.get('value'))

					if prop_name and prop_value is not None:
						properties.append(EnhancedAXProperty(name=prop_name, value=prop_value))
				except Exception as e:
					# Skip problematic properties
					logger.debug(f'Warning: Could not process AX property {prop}: {e}')
					continue

		return EnhancedAXNode(
			ax_node_id=ax_node.get('nodeId', ''),
			ignored=ax_node.get('ignored', False),
			role=ax_node.get('role', {}).get('value') if ax_node.get('role') else None,
			name=ax_node.get('name', {}).get('value') if ax_node.get('name') else None,
			description=ax_node.get('description', {}).get('value') if ax_node.get('description') else None,
			properties=properties,
		)

	async def _get_viewport_size(self) -> tuple[float, float, float, float, float]:
		"""Get viewport dimensions, device pixel ratio, and scroll position using CDP."""
		try:
			start_viewport = time.time()
			cdp_client = await self.browser.get_cdp_client()
			session_id = await self._get_current_page_session_id()

			# Get the layout metrics which includes the visual viewport
			metrics = await cdp_client.send.Page.getLayoutMetrics(session_id=session_id)
			end_viewport = time.time()
			logger.debug(f'⏱️ Page.getLayoutMetrics() took {end_viewport - start_viewport:.3f} seconds')

			visual_viewport = metrics.get('visualViewport', {})
			layout_viewport = metrics.get('layoutViewport', {})
			content_size = metrics.get('contentSize', {})

			# IMPORTANT: Use CSS viewport instead of device pixel viewport
			# This fixes the coordinate mismatch on high-DPI displays
			css_visual_viewport = metrics.get('cssVisualViewport', {})
			css_layout_viewport = metrics.get('cssLayoutViewport', {})

			# Use CSS pixels (what JavaScript sees) instead of device pixels
			width = css_visual_viewport.get('clientWidth', css_layout_viewport.get('clientWidth', 1920.0))
			height = css_visual_viewport.get('clientHeight', css_layout_viewport.get('clientHeight', 1080.0))

			# Calculate device pixel ratio
			device_width = visual_viewport.get('clientWidth', width)
			css_width = css_visual_viewport.get('clientWidth', width)
			device_pixel_ratio = device_width / css_width if css_width > 0 else 1.0

			# Get current scroll position from the visual viewport
			scroll_x = css_visual_viewport.get('pageX', 0)
			scroll_y = css_visual_viewport.get('pageY', 0)

			return float(width), float(height), float(device_pixel_ratio), float(scroll_x), float(scroll_y)
		except Exception as e:
			logger.debug(f'⚠️  Viewport size detection failed: {e}')
			# Fallback to default viewport size
			return 1920.0, 1080.0, 1.0, 0.0, 0.0

	@time_execution_async('--build_enhanced_dom_tree')
	async def _build_enhanced_dom_tree(
		self, all_frame_data: dict[str, tuple[GetDocumentReturns, GetFullAXTreeReturns, CaptureSnapshotReturns]]
	) -> EnhancedDOMTreeNode:
		"""Build enhanced DOM tree from multiple frame data sources."""

		# Get main frame data
		main_frame_data = all_frame_data.get('main')
		if not main_frame_data:
			raise ValueError('No main frame data available')

		main_dom_tree, main_ax_tree, main_snapshot = main_frame_data

		# Build AX tree lookup for main frame
		main_ax_tree_lookup: dict[int, AXNode] = {
			ax_node['backendDOMNodeId']: ax_node for ax_node in main_ax_tree['nodes'] if 'backendDOMNodeId' in ax_node
		}

		enhanced_dom_tree_node_lookup: dict[int, EnhancedDOMTreeNode] = {}
		""" NodeId (NOT backend node id) -> enhanced dom tree node"""  # way to get the parent/content node

		# Get viewport dimensions first for visibility calculation
		viewport_width, viewport_height, device_pixel_ratio, scroll_x, scroll_y = await self._get_viewport_size()

		# Parse snapshot data with everything calculated upfront for main frame
		main_snapshot_lookup = build_snapshot_lookup(
			main_snapshot, viewport_width, viewport_height, device_pixel_ratio, scroll_x, scroll_y
		)

		# Build snapshot lookups for all iframe frames
		iframe_snapshot_lookups: dict[str, dict[int, Any]] = {}
		iframe_ax_lookups: dict[str, dict[int, AXNode]] = {}

		for frame_id, (dom_tree, ax_tree, snapshot) in all_frame_data.items():
			if frame_id != 'main':
				# Build snapshot lookup for this iframe
				iframe_snapshot_lookups[frame_id] = build_snapshot_lookup(
					snapshot, viewport_width, viewport_height, device_pixel_ratio, scroll_x, scroll_y
				)
				# Build AX lookup for this iframe
				iframe_ax_lookups[frame_id] = {
					ax_node['backendDOMNodeId']: ax_node for ax_node in ax_tree['nodes'] if 'backendDOMNodeId' in ax_node
				}

		@time_execution_sync('--construct_enhanced_node')
		def _construct_enhanced_node(node: Node, frame_context: str = 'main') -> EnhancedDOMTreeNode:
			# memoize the mf (I don't know if some nodes are duplicated)
			if node['nodeId'] in enhanced_dom_tree_node_lookup:
				return enhanced_dom_tree_node_lookup[node['nodeId']]

			# Determine which lookups to use based on frame context
			if frame_context == 'main':
				ax_tree_lookup = main_ax_tree_lookup
				snapshot_lookup = main_snapshot_lookup
			else:
				ax_tree_lookup = iframe_ax_lookups.get(frame_context, {})
				snapshot_lookup = iframe_snapshot_lookups.get(frame_context, {})

			ax_node = ax_tree_lookup.get(node['backendNodeId'])
			if ax_node:
				enhanced_ax_node = self._build_enhanced_ax_node(ax_node)
			else:
				enhanced_ax_node = None

			# To make attributes more readable
			attributes: dict[str, str] | None = None
			if 'attributes' in node and node['attributes']:
				attributes = {}
				for i in range(0, len(node['attributes']), 2):
					attributes[node['attributes'][i]] = node['attributes'][i + 1]

			shadow_root_type = None
			if 'shadowRootType' in node and node['shadowRootType']:
				try:
					shadow_root_type = node['shadowRootType']
				except ValueError:
					pass

			dom_tree_node = EnhancedDOMTreeNode(
				node_id=node['nodeId'],
				backend_node_id=node['backendNodeId'],
				node_type=NodeType(node['nodeType']),
				node_name=node['nodeName'],
				node_value=node['nodeValue'],
				attributes=attributes or {},
				is_scrollable=node.get('isScrollable', None),
				frame_id=node.get('frameId', None),
				content_document=None,
				shadow_root_type=shadow_root_type,
				shadow_roots=None,
				parent_node=None,
				children_nodes=None,
				ax_node=enhanced_ax_node,
				snapshot_node=snapshot_lookup.get(node['backendNodeId'], None),
			)

			enhanced_dom_tree_node_lookup[node['nodeId']] = dom_tree_node

			if 'parentId' in node and node['parentId']:
				dom_tree_node.parent_node = enhanced_dom_tree_node_lookup[
					node['parentId']
				]  # parents should always be in the lookup

			if 'contentDocument' in node and node['contentDocument']:
				# For iframe content documents, we need to determine the frame context
				# This is where iframe piercing happens - we process the content document
				# with the appropriate frame context (snapshot/ax data from the iframe's session)
				content_frame_context = frame_context  # Default to current context

				# Try to find matching iframe frame data
				if node['nodeName'].lower() == 'iframe':
					# Look for iframe data that might match this content document
					for iframe_frame_id in iframe_snapshot_lookups.keys():
						if iframe_frame_id != 'main':
							content_frame_context = iframe_frame_id
							break  # Use first available iframe context for now
							# TODO: Better matching between iframe elements and their frame contexts

				# Process the content document
				content_doc = _construct_enhanced_node(node['contentDocument'], content_frame_context)

				# CRITICAL FIX: Set up proper parent relationship for iframe content
				# The content document's parent should be the iframe element, not None
				# This enables elements inside iframes to trace back to the iframe container
				content_doc.parent_node = dom_tree_node
				dom_tree_node.content_document = content_doc

			if 'shadowRoots' in node and node['shadowRoots']:
				dom_tree_node.shadow_roots = []
				for shadow_root in node['shadowRoots']:
					dom_tree_node.shadow_roots.append(_construct_enhanced_node(shadow_root, frame_context))

			if 'children' in node and node['children']:
				dom_tree_node.children_nodes = []
				for child in node['children']:
					dom_tree_node.children_nodes.append(_construct_enhanced_node(child, frame_context))

			return dom_tree_node

		enhanced_dom_tree_node = _construct_enhanced_node(main_dom_tree['root'])

		return enhanced_dom_tree_node

	@time_execution_async('--get_all_trees_with_iframe_support')
	async def _get_all_trees_with_iframe_support(
		self,
	) -> tuple[dict[str, tuple[GetDocumentReturns, GetFullAXTreeReturns, CaptureSnapshotReturns]], dict[str, float]]:
		"""Get DOM, AX, and Snapshot trees with iframe content included via pierce=true."""
		if not self.browser.cdp_url:
			raise ValueError('CDP URL is not set')

		session_id = await self._get_current_page_session_id()
		cdp_client = await self.browser.get_cdp_client()

		# Use pierce=true to get iframe content documents included in the main DOM tree
		logger.debug('⏱️ Starting CDP data retrieval calls...')

		# Time each major CDP call individually
		start_snapshot = time.time()
		snapshot_request = cdp_client.send.DOMSnapshot.captureSnapshot(
			params={
				'computedStyles': REQUIRED_COMPUTED_STYLES,
				'includePaintOrder': True,
				'includeDOMRects': True,
				'includeBlendedBackgroundColors': False,
				'includeTextColorOpacities': False,
			},
			session_id=session_id,
		)

		# Pierce=true includes iframe content documents
		start_dom = time.time()
		dom_tree_request = cdp_client.send.DOM.getDocument(params={'depth': -1, 'pierce': True}, session_id=session_id)

		start_ax = time.time()
		ax_tree_request = cdp_client.send.Accessibility.getFullAXTree(session_id=session_id)

		logger.debug('⏱️ All CDP requests initiated, waiting for responses...')
		start_gather = time.time()
		snapshot, dom_tree, ax_tree = await asyncio.gather(snapshot_request, dom_tree_request, ax_tree_request)
		end_gather = time.time()

		# Calculate individual timings (approximate since they overlap)
		snapshot_time = end_gather - start_snapshot
		dom_time = end_gather - start_dom
		ax_time = end_gather - start_ax
		total_time = end_gather - start_snapshot

		logger.debug(f'⏱️ DOMSnapshot.captureSnapshot() took ~{snapshot_time:.3f} seconds')
		logger.debug(f'⏱️ DOM.getDocument() took ~{dom_time:.3f} seconds')
		logger.debug(f'⏱️ Accessibility.getFullAXTree() took ~{ax_time:.3f} seconds')
		logger.debug(f'⏱️ Total CDP data retrieval took {total_time:.3f} seconds')

		cdp_timing = {
			'cdp_calls_total': total_time,
			'cdp_snapshot_time': snapshot_time,
			'cdp_dom_time': dom_time,
			'cdp_ax_time': ax_time,
		}
		logger.debug(f'⏳ Time taken to get DOM tree with iframe content: {total_time:.3f} seconds')

		# Return single frame data - the iframe content is embedded in the main DOM tree
		all_frame_data = {'main': (dom_tree, ax_tree, snapshot)}
		return all_frame_data, cdp_timing

	@time_execution_async('--get_all_trees')
	async def _get_all_trees(self) -> tuple[CaptureSnapshotReturns, GetDocumentReturns, GetFullAXTreeReturns, dict[str, float]]:
		if not self.browser.cdp_url:
			raise ValueError('CDP URL is not set')

		session_id = await self._get_current_page_session_id()
		cdp_client = await self.browser.get_cdp_client()

		snapshot_request = cdp_client.send.DOMSnapshot.captureSnapshot(
			params={
				'computedStyles': REQUIRED_COMPUTED_STYLES,
				'includePaintOrder': True,
				'includeDOMRects': True,
				'includeBlendedBackgroundColors': False,
				'includeTextColorOpacities': False,
			},
			session_id=session_id,
		)

		dom_tree_request = cdp_client.send.DOM.getDocument(params={'depth': -1, 'pierce': True}, session_id=session_id)

		ax_tree_request = cdp_client.send.Accessibility.getFullAXTree(session_id=session_id)

		start = time.time()
		snapshot, dom_tree, ax_tree = await asyncio.gather(snapshot_request, dom_tree_request, ax_tree_request)
		end = time.time()
		cdp_timing = {'cdp_calls_total': end - start}
		logger.debug(f'Time taken to get dom tree: {end - start} seconds')

		return snapshot, dom_tree, ax_tree, cdp_timing

	@time_execution_async('--get_dom_tree')
	@observe_debug(ignore_input=True, ignore_output=True, name='get_dom_tree')
	async def get_dom_tree(self) -> tuple[EnhancedDOMTreeNode, dict[str, float]]:
		"""Get enhanced DOM tree with iframe piercing support."""
		# Use the new iframe-aware method
		all_frame_data, cdp_timing = await self._get_all_trees_with_iframe_support()

		start = time.time()
		enhanced_dom_tree = await self._build_enhanced_dom_tree(all_frame_data)
		end = time.time()

		build_tree_timing = {'build_enhanced_dom_tree': end - start}
		logger.debug(f'Time taken to build enhanced dom tree: {end - start} seconds')

		# Combine timing info
		all_timing = {**cdp_timing, **build_tree_timing}
		return enhanced_dom_tree, all_timing

	@time_execution_async('--get_serialized_dom_tree')
	@observe_debug(ignore_input=True, ignore_output=True, name='get_serialized_dom_tree')
	async def get_serialized_dom_tree(
		self, previous_cached_state: SerializedDOMState | None = None
	) -> tuple[SerializedDOMState, dict[str, float]]:
		"""Get the serialized DOM tree representation for LLM consumption.

		TODO: this is a bit of a hack, we should probably have a better way to do this
		"""
		enhanced_dom_tree, dom_timing = await self.get_dom_tree()

		start = time.time()
		serialized_dom_state, serializer_timing = DOMTreeSerializer(
			enhanced_dom_tree, previous_cached_state
		).serialize_accessible_elements()

		end = time.time()
		serialize_total_timing = {'serialize_dom_tree_total': end - start}
		logger.debug(f'Time taken to serialize dom tree: {end - start} seconds')

		# Combine all timing info
		all_timing = {**dom_timing, **serializer_timing, **serialize_total_timing}
		return serialized_dom_state, all_timing
