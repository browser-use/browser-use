"""
Enhanced snapshot processing for browser-use DOM tree extraction.

This module provides stateless functions for parsing Chrome DevTools Protocol (CDP) DOMSnapshot data
to extract visibility, clickability, cursor styles, and other layout information.
"""

from cdp_use.cdp.domsnapshot.commands import CaptureSnapshotReturns
from cdp_use.cdp.domsnapshot.types import (
	DocumentSnapshot,
	LayoutTreeSnapshot,
	NodeTreeSnapshot,
	RareBooleanData,
)

from browser_use.dom.views import DOMRect, EnhancedSnapshotNode
from browser_use.utils import time_execution_sync

# Only the ESSENTIAL computed styles for interactivity and visibility detection
REQUIRED_COMPUTED_STYLES = [
	# Essential for visibility
	'display',
	'visibility',
	'opacity',
	'position',
	'z-index',
	'pointer-events',
	'cursor',
	'overflow',
	'overflow-x',
	'overflow-y',
	'width',
	'height',
	'top',
	'left',
	'right',
	'bottom',
	'transform',
	'clip',
	'clip-path',
	'user-select',
	'background-color',
	'color',
	'border',
	'margin',
	'padding',
]


def _parse_rare_boolean_data(rare_data: RareBooleanData, index: int) -> bool | None:
	"""Parse rare boolean data from snapshot - returns True if index is in the rare data."""
	return index in rare_data['index']


def _parse_computed_styles(strings: list[str], style_indices: list[int]) -> dict[str, str]:
	"""Parse computed styles from layout tree using string indices."""
	styles = {}
	for i, style_index in enumerate(style_indices):
		if i < len(REQUIRED_COMPUTED_STYLES) and 0 <= style_index < len(strings):
			styles[REQUIRED_COMPUTED_STYLES[i]] = strings[style_index]
	return styles


def _is_element_visible(
	bounding_box: DOMRect,
	computed_styles: dict[str, str],
	viewport_width: float,
	viewport_height: float,
	scroll_x: float = 0.0,
	scroll_y: float = 0.0,
) -> bool:
	"""Determine if an element is visible in the current scrolled viewport with robust edge case handling."""

	# Validate inputs - handle edge cases gracefully
	if not bounding_box or viewport_width <= 0 or viewport_height <= 0:
		return False

	# Check CSS visibility properties
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

	# SCROLL-AWARE VISIBILITY: Check if element intersects with current scrolled viewport
	# Current viewport rectangle in document coordinates
	viewport_left = scroll_x
	viewport_top = scroll_y
	viewport_right = scroll_x + viewport_width
	viewport_bottom = scroll_y + viewport_height

	# Element rectangle in document coordinates
	elem_left = bounding_box.x
	elem_top = bounding_box.y
	elem_right = bounding_box.x + bounding_box.width
	elem_bottom = bounding_box.y + bounding_box.height

	# Check if rectangles intersect (element is visible in current viewport)
	intersects = (
		elem_right > viewport_left and elem_left < viewport_right and elem_bottom > viewport_top and elem_top < viewport_bottom
	)

	return intersects


@time_execution_sync('--build_snapshot_lookup')
def build_snapshot_lookup(
	snapshot: CaptureSnapshotReturns,
	viewport_width: float,
	viewport_height: float,
	device_pixel_ratio: float = 1.0,
	scroll_x: float = 0.0,
	scroll_y: float = 0.0,
) -> dict[int, EnhancedSnapshotNode]:
	"""Build a lookup table of backend node ID to enhanced snapshot data with everything calculated upfront."""
	snapshot_lookup: dict[int, EnhancedSnapshotNode] = {}

	if not snapshot['documents']:
		return snapshot_lookup

	document: DocumentSnapshot = snapshot['documents'][0]
	strings = snapshot['strings']
	nodes: NodeTreeSnapshot = document['nodes']
	layout: LayoutTreeSnapshot = document['layout']

	# Build backend node id to snapshot index lookup
	backend_node_to_snapshot_index = {}
	if 'backendNodeId' in nodes:
		for i, backend_node_id in enumerate(nodes['backendNodeId']):
			backend_node_to_snapshot_index[backend_node_id] = i

	# 🚀 OPTIMIZATION 1: Pre-build layout lookup table (eliminates O(n²) nested loop)
	snapshot_index_to_layout_idx = {}
	layout_node_indices = layout.get('nodeIndex', [])
	for layout_idx, node_index in enumerate(layout_node_indices):
		snapshot_index_to_layout_idx[node_index] = layout_idx

	# 🚀 OPTIMIZATION 2: Cache layout arrays (eliminates repeated .get() calls)
	layout_bounds = layout.get('bounds', [])
	layout_styles = layout.get('styles', [])
	layout_paint_orders = layout.get('paintOrders', [])
	layout_client_rects = layout.get('clientRects', [])
	layout_stacking_contexts = layout.get('stackingContexts', {})
	stacking_contexts_indices = layout_stacking_contexts.get('index', [])

	# ⚡ OPTIMIZATION 3: Pre-extract clickable data
	nodes_is_clickable = nodes.get('isClickable')

	# Build snapshot lookup for each backend node id
	for backend_node_id, snapshot_index in backend_node_to_snapshot_index.items():
		# ⚡ Fast clickable check
		is_clickable = None
		if nodes_is_clickable:
			is_clickable = _parse_rare_boolean_data(nodes_is_clickable, snapshot_index)

		# 🚀 OPTIMIZATION 4: O(1) layout lookup instead of O(n) search
		cursor_style = None
		is_visible = None
		bounding_box = None
		computed_styles = {}
		paint_order = None
		client_rects = None
		stacking_contexts = None

		# Fast layout lookup using pre-built index
		layout_idx = snapshot_index_to_layout_idx.get(snapshot_index)
		if layout_idx is not None and layout_idx < len(layout_bounds):
			# Parse bounding box
			bounds = layout_bounds[layout_idx]
			if len(bounds) >= 4:
				# IMPORTANT: CDP coordinates are in device pixels, convert to CSS pixels
				# by dividing by the device pixel ratio
				raw_x, raw_y, raw_width, raw_height = bounds[0], bounds[1], bounds[2], bounds[3]

				# Apply device pixel ratio scaling to convert device pixels to CSS pixels
				bounding_box = DOMRect(
					x=raw_x / device_pixel_ratio,
					y=raw_y / device_pixel_ratio,
					width=raw_width / device_pixel_ratio,
					height=raw_height / device_pixel_ratio,
				)

			# Parse computed styles for this layout node
			if layout_idx < len(layout_styles):
				style_indices = layout_styles[layout_idx]
				computed_styles = _parse_computed_styles(strings, style_indices)
				cursor_style = computed_styles.get('cursor')

			# Extract paint order if available
			if layout_idx < len(layout_paint_orders):
				paint_order = layout_paint_orders[layout_idx]

			# Extract client rects if available
			if layout_idx < len(layout_client_rects):
				client_rect_data = layout_client_rects[layout_idx]
				if client_rect_data and len(client_rect_data) >= 4:
					client_rects = DOMRect(
						x=client_rect_data[0],
						y=client_rect_data[1],
						width=client_rect_data[2],
						height=client_rect_data[3],
					)

			# Extract stacking contexts if available
			if layout_idx < len(stacking_contexts_indices):
				stacking_contexts = stacking_contexts_indices[layout_idx]

			# Calculate scroll-aware visibility if we have bounding box
			if bounding_box and computed_styles:
				is_visible = _is_element_visible(
					bounding_box, computed_styles, viewport_width, viewport_height, scroll_x, scroll_y
				)

		snapshot_lookup[backend_node_id] = EnhancedSnapshotNode(
			is_clickable=is_clickable,
			cursor_style=cursor_style,
			is_visible=is_visible,
			bounds=bounding_box,
			# clientRects=client_rects,
			computed_styles=computed_styles if computed_styles else None,
			paint_order=paint_order,
			stacking_contexts=stacking_contexts,
		)

	return snapshot_lookup
