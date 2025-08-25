import asyncio
import logging
import time
from typing import TYPE_CHECKING

from cdp_use.cdp.accessibility.commands import GetFullAXTreeReturns
from cdp_use.cdp.accessibility.types import AXNode
from cdp_use.cdp.dom.types import Node
from cdp_use.cdp.target import TargetID

from browser_use.dom.enhanced_snapshot import (
	REQUIRED_COMPUTED_STYLES,
	build_snapshot_lookup,
)
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import (
	CurrentPageTargets,
	DOMRect,
	EnhancedAXNode,
	EnhancedAXProperty,
	EnhancedDOMTreeNode,
	NodeType,
	SerializedDOMState,
	TargetAllTrees,
)

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession


class DomService:
	"""
	Service for getting the DOM tree and other DOM-related information.

	Either browser or page must be provided.

	TODO: currently we start a new websocket connection PER STEP, we should definitely keep this persistent
	"""

	logger: logging.Logger

	def __init__(
		self, browser_session: 'BrowserSession', logger: logging.Logger | None = None, cross_origin_iframes: bool = False
	):
		self.browser_session = browser_session
		self.logger = logger or browser_session.logger
		self.cross_origin_iframes = cross_origin_iframes

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc_value, traceback):
		pass  # no need to cleanup anything, browser_session auto handles cleaning up session cache

	async def _get_targets_for_page(self, target_id: TargetID | None = None) -> CurrentPageTargets:
		"""Get the target info for a specific page.

		Args:
			target_id: The target ID to get info for. If None, uses current_target_id.
		"""
		targets = await self.browser_session.cdp_client.send.Target.getTargets()

		# Use provided target_id or fall back to current_target_id
		if target_id is None:
			target_id = self.browser_session.current_target_id
			if not target_id:
				raise ValueError('No current target ID set in browser session')

		# Find main page target by ID
		main_target = next((t for t in targets['targetInfos'] if t['targetId'] == target_id), None)

		if not main_target:
			raise ValueError(f'No target found for target ID: {target_id}')

		# Get all frames using the new method to find iframe targets for this page
		all_frames, _ = await self.browser_session.get_all_frames()

		# Find iframe targets that are children of this target
		iframe_targets = []
		for frame_info in all_frames.values():
			# Check if this frame is a cross-origin iframe with its own target
			if frame_info.get('isCrossOrigin') and frame_info.get('frameTargetId'):
				# Check if this frame belongs to our target
				parent_target = frame_info.get('parentTargetId', frame_info.get('frameTargetId'))
				if parent_target == target_id:
					# Find the target info for this iframe
					iframe_target = next(
						(t for t in targets['targetInfos'] if t['targetId'] == frame_info['frameTargetId']), None
					)
					if iframe_target:
						iframe_targets.append(iframe_target)

		return CurrentPageTargets(
			page_session=main_target,
			iframe_sessions=iframe_targets,
		)

	def _build_enhanced_ax_node(self, ax_node: AXNode) -> EnhancedAXNode:
		properties: list[EnhancedAXProperty] | None = None
		if 'properties' in ax_node and ax_node['properties']:
			properties = []
			for property in ax_node['properties']:
				try:
					# test whether property name can go into the enum (sometimes Chrome returns some random properties)
					properties.append(
						EnhancedAXProperty(
							name=property['name'],
							value=property.get('value', {}).get('value', None),
							# related_nodes=[],  # TODO: add related nodes
						)
					)
				except ValueError:
					pass

		enhanced_ax_node = EnhancedAXNode(
			ax_node_id=ax_node['nodeId'],
			ignored=ax_node['ignored'],
			role=ax_node.get('role', {}).get('value', None),
			name=ax_node.get('name', {}).get('value', None),
			description=ax_node.get('description', {}).get('value', None),
			properties=properties,
		)
		return enhanced_ax_node

	async def _get_viewport_ratio(self, target_id: TargetID) -> float:
		"""Get viewport dimensions, device pixel ratio, and scroll position using CDP."""
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=True)

		try:
			# Get the layout metrics which includes the visual viewport
			metrics = await cdp_session.cdp_client.send.Page.getLayoutMetrics(session_id=cdp_session.session_id)

			visual_viewport = metrics.get('visualViewport', {})

			# IMPORTANT: Use CSS viewport instead of device pixel viewport
			# This fixes the coordinate mismatch on high-DPI displays
			css_visual_viewport = metrics.get('cssVisualViewport', {})
			css_layout_viewport = metrics.get('cssLayoutViewport', {})

			# Use CSS pixels (what JavaScript sees) instead of device pixels
			width = css_visual_viewport.get('clientWidth', css_layout_viewport.get('clientWidth', 1920.0))

			# Calculate device pixel ratio
			device_width = visual_viewport.get('clientWidth', width)
			css_width = css_visual_viewport.get('clientWidth', width)
			device_pixel_ratio = device_width / css_width if css_width > 0 else 1.0

			return float(device_pixel_ratio)
		except Exception as e:
			self.logger.debug(f'Viewport size detection failed: {e}')
			# Fallback to default viewport size
			return 1.0

	@classmethod
	def is_element_visible_according_to_all_parents(
		cls, node: EnhancedDOMTreeNode, html_frames: list[EnhancedDOMTreeNode]
	) -> bool:
		"""Check if the element is visible according to all its parent HTML frames."""

		if not node.snapshot_node:
			return False

		computed_styles = node.snapshot_node.computed_styles or {}

		display = computed_styles.get('display', '').lower()
		visibility = computed_styles.get('visibility', '').lower()
		opacity = computed_styles.get('opacity', '1')

		if display == 'none' or visibility == 'hidden':
			return False

		try:
			if float(opacity) <= 0:
				return False
		except (ValueError, TypeError):
			pass

		# Start with the element's local bounds (in its own frame's coordinate system)
		current_bounds = node.snapshot_node.bounds

		if not current_bounds:
			return False  # If there are no bounds, the element is not visible

		"""
		Reverse iterate through the html frames (that can be either iframe or document -> if it's a document frame compare if the current bounds interest with it (taking scroll into account) otherwise move the current bounds by the iframe offset)
		"""
		for frame in reversed(html_frames):
			if (
				frame.node_type == NodeType.ELEMENT_NODE
				and frame.node_name.upper() == 'IFRAME'
				and frame.snapshot_node
				and frame.snapshot_node.bounds
			):
				iframe_bounds = frame.snapshot_node.bounds

				# negate the values added in `_construct_enhanced_node`
				current_bounds.x += iframe_bounds.x
				current_bounds.y += iframe_bounds.y

			if (
				frame.node_type == NodeType.ELEMENT_NODE
				and frame.node_name == 'HTML'
				and frame.snapshot_node
				and frame.snapshot_node.scrollRects
				and frame.snapshot_node.clientRects
			):
				# For iframe content, we need to check visibility within the iframe's viewport
				# The scrollRects represent the current scroll position
				# The clientRects represent the viewport size
				# Elements are visible if they fall within the viewport after accounting for scroll

				# The viewport of the frame (what's actually visible)
				viewport_left = 0  # Viewport always starts at 0 in frame coordinates
				viewport_top = 0
				viewport_right = frame.snapshot_node.clientRects.width
				viewport_bottom = frame.snapshot_node.clientRects.height

				# Adjust element bounds by the scroll offset to get position relative to viewport
				# When scrolled down, scrollRects.y is positive, so we subtract it from element's y
				adjusted_x = current_bounds.x - frame.snapshot_node.scrollRects.x
				adjusted_y = current_bounds.y - frame.snapshot_node.scrollRects.y

				frame_intersects = (
					adjusted_x < viewport_right
					and adjusted_x + current_bounds.width > viewport_left
					and adjusted_y < viewport_bottom
					and adjusted_y + current_bounds.height > viewport_top
				)

				if not frame_intersects:
					return False

				# Keep the original coordinate adjustment to maintain consistency
				# This adjustment is needed for proper coordinate transformation
				current_bounds.x -= frame.snapshot_node.scrollRects.x
				current_bounds.y -= frame.snapshot_node.scrollRects.y

		# If we reach here, element is visible in main viewport and all containing iframes
		return True

	async def _get_ax_tree_for_all_frames(self, target_id: TargetID) -> GetFullAXTreeReturns:
		"""Recursively collect all frames and merge their accessibility trees into a single array."""

		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=False)
		frame_tree = await cdp_session.cdp_client.send.Page.getFrameTree(session_id=cdp_session.session_id)

		def collect_all_frame_ids(frame_tree_node) -> list[str]:
			"""Recursively collect all frame IDs from the frame tree."""
			frame_ids = [frame_tree_node['frame']['id']]

			if 'childFrames' in frame_tree_node and frame_tree_node['childFrames']:
				for child_frame in frame_tree_node['childFrames']:
					frame_ids.extend(collect_all_frame_ids(child_frame))

			return frame_ids

		# Collect all frame IDs recursively
		all_frame_ids = collect_all_frame_ids(frame_tree['frameTree'])

		# Get accessibility tree for each frame
		ax_tree_requests = []
		for frame_id in all_frame_ids:
			ax_tree_request = cdp_session.cdp_client.send.Accessibility.getFullAXTree(
				params={'frameId': frame_id}, session_id=cdp_session.session_id
			)
			ax_tree_requests.append(ax_tree_request)

		# Wait for all requests to complete
		ax_trees = await asyncio.gather(*ax_tree_requests)

		# Merge all AX nodes into a single array
		merged_nodes: list[AXNode] = []
		for ax_tree in ax_trees:
			merged_nodes.extend(ax_tree['nodes'])

		return {'nodes': merged_nodes}

	async def _get_all_trees(self, target_id: TargetID) -> TargetAllTrees:
		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=False)

		# Wait for the page to be ready first
		try:
			ready_state = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': 'document.readyState'}, session_id=cdp_session.session_id
			)
		except Exception as e:
			pass  # Page might not be ready yet
		# DEBUG: Log before capturing snapshot
		self.logger.debug(f'🔍 DEBUG: Capturing DOM snapshot for target {target_id}')

		# Get actual scroll positions for all iframes before capturing snapshot
		iframe_scroll_positions = {}
		try:
			scroll_result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': """
					(() => {
						const scrollData = {};
						const iframes = document.querySelectorAll('iframe');
						iframes.forEach((iframe, index) => {
							try {
								const doc = iframe.contentDocument || iframe.contentWindow.document;
								if (doc) {
									scrollData[index] = {
										scrollTop: doc.documentElement.scrollTop || doc.body.scrollTop || 0,
										scrollLeft: doc.documentElement.scrollLeft || doc.body.scrollLeft || 0
									};
								}
							} catch (e) {
								// Cross-origin iframe, can't access
							}
						});
						return scrollData;
					})()
					""",
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			if scroll_result and 'result' in scroll_result and 'value' in scroll_result['result']:
				iframe_scroll_positions = scroll_result['result']['value']
				for idx, scroll_data in iframe_scroll_positions.items():
					self.logger.debug(
						f'🔍 DEBUG: Iframe {idx} actual scroll position - scrollTop={scroll_data.get("scrollTop", 0)}, scrollLeft={scroll_data.get("scrollLeft", 0)}'
					)
		except Exception as e:
			self.logger.debug(f'Failed to get iframe scroll positions: {e}')

		# Define CDP request factories to avoid duplication
		def create_snapshot_request():
			return cdp_session.cdp_client.send.DOMSnapshot.captureSnapshot(
				params={
					'computedStyles': REQUIRED_COMPUTED_STYLES,
					'includePaintOrder': True,
					'includeDOMRects': True,
					'includeBlendedBackgroundColors': False,
					'includeTextColorOpacities': False,
				},
				session_id=cdp_session.session_id,
			)

		def create_dom_tree_request():
			return cdp_session.cdp_client.send.DOM.getDocument(
				params={'depth': -1, 'pierce': True}, session_id=cdp_session.session_id
			)

		start = time.time()

		# Create initial tasks
		tasks = {
			'snapshot': asyncio.create_task(create_snapshot_request()),
			'dom_tree': asyncio.create_task(create_dom_tree_request()),
			'ax_tree': asyncio.create_task(self._get_ax_tree_for_all_frames(target_id)),
			'device_pixel_ratio': asyncio.create_task(self._get_viewport_ratio(target_id)),
		}

		# Wait for all tasks with timeout
		done, pending = await asyncio.wait(tasks.values(), timeout=10.0)

		# Retry any failed or timed out tasks
		if pending:
			for task in pending:
				task.cancel()

			# Retry mapping for pending tasks
			retry_map = {
				tasks['snapshot']: lambda: asyncio.create_task(create_snapshot_request()),
				tasks['dom_tree']: lambda: asyncio.create_task(create_dom_tree_request()),
				tasks['ax_tree']: lambda: asyncio.create_task(self._get_ax_tree_for_all_frames(target_id)),
				tasks['device_pixel_ratio']: lambda: asyncio.create_task(self._get_viewport_ratio(target_id)),
			}

			# Create new tasks only for the ones that didn't complete
			for key, task in tasks.items():
				if task in pending and task in retry_map:
					tasks[key] = retry_map[task]()

			# Wait again with shorter timeout
			done2, pending2 = await asyncio.wait([t for t in tasks.values() if not t.done()], timeout=2.0)

			if pending2:
				for task in pending2:
					task.cancel()

		# Extract results, tracking which ones failed
		results = {}
		failed = []
		for key, task in tasks.items():
			if task.done() and not task.cancelled():
				try:
					results[key] = task.result()
				except Exception as e:
					self.logger.warning(f'CDP request {key} failed with exception: {e}')
					failed.append(key)
			else:
				self.logger.warning(f'CDP request {key} timed out')
				failed.append(key)

		# If any required tasks failed, raise an exception
		if failed:
			raise TimeoutError(f'CDP requests failed or timed out: {", ".join(failed)}')

		snapshot = results['snapshot']
		dom_tree = results['dom_tree']
		ax_tree = results['ax_tree']
		device_pixel_ratio = results['device_pixel_ratio']
		end = time.time()
		cdp_timing = {'cdp_calls_total': end - start}

		# DEBUG: Log snapshot info
		if snapshot and 'documents' in snapshot:
			total_nodes = sum(len(doc.get('nodes', [])) for doc in snapshot['documents'])
			self.logger.debug(
				f'🔍 DEBUG: Snapshot contains {len(snapshot["documents"])} documents with {total_nodes} total nodes'
			)
			# Log iframe-specific info
			for doc_idx, doc in enumerate(snapshot['documents']):
				if doc_idx > 0:  # Not the main document
					self.logger.debug(f'🔍 DEBUG: Document {doc_idx} has {len(doc.get("nodes", []))} nodes')

		return TargetAllTrees(
			snapshot=snapshot,
			dom_tree=dom_tree,
			ax_tree=ax_tree,
			device_pixel_ratio=device_pixel_ratio,
			cdp_timing=cdp_timing,
		)

	async def get_dom_tree(
		self,
		target_id: TargetID,
		initial_html_frames: list[EnhancedDOMTreeNode] | None = None,
		initial_total_frame_offset: DOMRect | None = None,
	) -> EnhancedDOMTreeNode:
		"""Get the DOM tree for a specific target.

		Args:
			target_id: Target ID of the page to get the DOM tree for.
			initial_html_frames: List of HTML frame nodes encountered so far
			initial_total_frame_offset: Accumulated coordinate offset
		"""

		trees = await self._get_all_trees(target_id)

		dom_tree = trees.dom_tree
		ax_tree = trees.ax_tree
		snapshot = trees.snapshot
		device_pixel_ratio = trees.device_pixel_ratio

		ax_tree_lookup: dict[int, AXNode] = {
			ax_node['backendDOMNodeId']: ax_node for ax_node in ax_tree['nodes'] if 'backendDOMNodeId' in ax_node
		}

		enhanced_dom_tree_node_lookup: dict[int, EnhancedDOMTreeNode] = {}
		""" NodeId (NOT backend node id) -> enhanced dom tree node"""  # way to get the parent/content node

		# Parse snapshot data with everything calculated upfront
		snapshot_lookup = build_snapshot_lookup(snapshot, device_pixel_ratio)

		async def _construct_enhanced_node(
			node: Node, html_frames: list[EnhancedDOMTreeNode] | None, total_frame_offset: DOMRect | None
		) -> EnhancedDOMTreeNode:
			"""
			Recursively construct enhanced DOM tree nodes.

			Args:
				node: The DOM node to construct
				html_frames: List of HTML frame nodes encountered so far
				accumulated_iframe_offset: Accumulated coordinate translation from parent iframes (includes scroll corrections)
			"""

			# Initialize lists if not provided
			if html_frames is None:
				html_frames = []

			# to get rid of the pointer references
			if total_frame_offset is None:
				total_frame_offset = DOMRect(x=0.0, y=0.0, width=0.0, height=0.0)
			else:
				total_frame_offset = DOMRect(
					total_frame_offset.x, total_frame_offset.y, total_frame_offset.width, total_frame_offset.height
				)

			# memoize the mf (I don't know if some nodes are duplicated)
			if node['nodeId'] in enhanced_dom_tree_node_lookup:
				return enhanced_dom_tree_node_lookup[node['nodeId']]

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

			# Get snapshot data and calculate absolute position
			snapshot_data = snapshot_lookup.get(node['backendNodeId'], None)
			absolute_position = None
			if snapshot_data and snapshot_data.bounds:
				absolute_position = DOMRect(
					x=snapshot_data.bounds.x + total_frame_offset.x,
					y=snapshot_data.bounds.y + total_frame_offset.y,
					width=snapshot_data.bounds.width,
					height=snapshot_data.bounds.height,
				)

			dom_tree_node = EnhancedDOMTreeNode(
				node_id=node['nodeId'],
				backend_node_id=node['backendNodeId'],
				node_type=NodeType(node['nodeType']),
				node_name=node['nodeName'],
				node_value=node['nodeValue'],
				attributes=attributes or {},
				is_scrollable=node.get('isScrollable', None),
				frame_id=node.get('frameId', None),
				session_id=self.browser_session.agent_focus.session_id if self.browser_session.agent_focus else None,
				target_id=target_id,
				content_document=None,
				shadow_root_type=shadow_root_type,
				shadow_roots=None,
				parent_node=None,
				children_nodes=None,
				ax_node=enhanced_ax_node,
				snapshot_node=snapshot_data,
				is_visible=None,
				absolute_position=absolute_position,
				element_index=None,
			)

			enhanced_dom_tree_node_lookup[node['nodeId']] = dom_tree_node

			if 'parentId' in node and node['parentId']:
				dom_tree_node.parent_node = enhanced_dom_tree_node_lookup[
					node['parentId']
				]  # parents should always be in the lookup

			# Check if this is an HTML frame node and add it to the list
			updated_html_frames = html_frames.copy()
			if node['nodeType'] == NodeType.ELEMENT_NODE.value and node['nodeName'] == 'HTML' and node.get('frameId') is not None:
				updated_html_frames.append(dom_tree_node)

				# and adjust the total frame offset by scroll
				if snapshot_data and snapshot_data.scrollRects:
					total_frame_offset.x -= snapshot_data.scrollRects.x
					total_frame_offset.y -= snapshot_data.scrollRects.y
					# DEBUG: Log iframe scroll information
					self.logger.debug(
						f'🔍 DEBUG: HTML frame scroll - scrollY={snapshot_data.scrollRects.y}, scrollX={snapshot_data.scrollRects.x}, frameId={node.get("frameId")}, nodeId={node["nodeId"]}'
					)

			# Calculate new iframe offset for content documents, accounting for iframe scroll
			if node['nodeName'].upper() == 'IFRAME' and snapshot_data and snapshot_data.bounds:
				if snapshot_data.bounds:
					updated_html_frames.append(dom_tree_node)

					total_frame_offset.x += snapshot_data.bounds.x
					total_frame_offset.y += snapshot_data.bounds.y

			if 'contentDocument' in node and node['contentDocument']:
				dom_tree_node.content_document = await _construct_enhanced_node(
					node['contentDocument'], updated_html_frames, total_frame_offset
				)
				dom_tree_node.content_document.parent_node = dom_tree_node
				# forcefully set the parent node to the content document node (helps traverse the tree)

			if 'shadowRoots' in node and node['shadowRoots']:
				dom_tree_node.shadow_roots = []
				for shadow_root in node['shadowRoots']:
					shadow_root_node = await _construct_enhanced_node(shadow_root, updated_html_frames, total_frame_offset)
					# forcefully set the parent node to the shadow root node (helps traverse the tree)
					shadow_root_node.parent_node = dom_tree_node
					dom_tree_node.shadow_roots.append(shadow_root_node)

			if 'children' in node and node['children']:
				dom_tree_node.children_nodes = []
				for child in node['children']:
					dom_tree_node.children_nodes.append(
						await _construct_enhanced_node(child, updated_html_frames, total_frame_offset)
					)

			# Set visibility using the collected HTML frames
			dom_tree_node.is_visible = self.is_element_visible_according_to_all_parents(dom_tree_node, updated_html_frames)

			# DEBUG: Log visibility info for form elements in iframes
			if dom_tree_node.tag_name and dom_tree_node.tag_name.upper() in ['INPUT', 'SELECT', 'TEXTAREA', 'LABEL']:
				attrs = dom_tree_node.attributes or {}
				elem_id = attrs.get('id', '')
				elem_name = attrs.get('name', '')
				if (
					'city' in elem_id.lower()
					or 'city' in elem_name.lower()
					or 'state' in elem_id.lower()
					or 'state' in elem_name.lower()
					or 'zip' in elem_id.lower()
					or 'zip' in elem_name.lower()
				):
					self.logger.debug(
						f"🔍 DEBUG: Form element {dom_tree_node.tag_name} id='{elem_id}' name='{elem_name}' - visible={dom_tree_node.is_visible}, bounds={dom_tree_node.snapshot_node.bounds if dom_tree_node.snapshot_node else 'NO_SNAPSHOT'}"
					)

			# handle cross origin iframe (just recursively call the main function with the proper target if it exists in iframes)
			# only do this if the iframe is visible (otherwise it's not worth it)

			if (
				# TODO: hacky way to disable cross origin iframes for now
				self.cross_origin_iframes and node['nodeName'].upper() == 'IFRAME' and node.get('contentDocument', None) is None
			):  # None meaning there is no content
				# Use get_all_frames to find the iframe's target
				frame_id = node.get('frameId', None)
				if frame_id:
					all_frames, _ = await self.browser_session.get_all_frames()
					frame_info = all_frames.get(frame_id)
					iframe_document_target = None
					if frame_info and frame_info.get('frameTargetId'):
						# Get the target info for this iframe
						targets = await self.browser_session.cdp_client.send.Target.getTargets()
						iframe_document_target = next(
							(t for t in targets['targetInfos'] if t['targetId'] == frame_info['frameTargetId']), None
						)
				else:
					iframe_document_target = None
				# if target actually exists in one of the frames, just recursively build the dom tree for it
				if iframe_document_target:
					self.logger.debug(f'Getting content document for iframe {node.get("frameId", None)}')
					content_document = await self.get_dom_tree(
						target_id=iframe_document_target.get('targetId'),
						# TODO: experiment with this values -> not sure whether the whole cross origin iframe should be ALWAYS included as soon as some part of it is visible or not.
						# Current config: if the cross origin iframe is AT ALL visible, then just include everything inside of it!
						# initial_html_frames=updated_html_frames,
						initial_total_frame_offset=total_frame_offset,
					)

					dom_tree_node.content_document = content_document
					dom_tree_node.content_document.parent_node = dom_tree_node

			return dom_tree_node

		enhanced_dom_tree_node = await _construct_enhanced_node(dom_tree['root'], initial_html_frames, initial_total_frame_offset)

		return enhanced_dom_tree_node

	async def get_serialized_dom_tree(
		self, previous_cached_state: SerializedDOMState | None = None
	) -> tuple[SerializedDOMState, EnhancedDOMTreeNode, dict[str, float]]:
		"""Get the serialized DOM tree representation for LLM consumption.

		Returns:
			Tuple of (serialized_dom_state, enhanced_dom_tree_root, timing_info)
		"""

		# Use current target (None means use current)
		assert self.browser_session.current_target_id is not None
		enhanced_dom_tree = await self.get_dom_tree(target_id=self.browser_session.current_target_id)

		start = time.time()
		serialized_dom_state, serializer_timing = DOMTreeSerializer(
			enhanced_dom_tree, previous_cached_state
		).serialize_accessible_elements()

		end = time.time()
		serialize_total_timing = {'serialize_dom_tree_total': end - start}

		# Combine all timing info
		all_timing = {**serializer_timing, **serialize_total_timing}

		return serialized_dom_state, enhanced_dom_tree, all_timing
