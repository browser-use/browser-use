"""Python-based highlighting system for drawing bounding boxes on screenshots.

This module replaces JavaScript-based highlighting with fast Python image processing
to draw bounding boxes around interactive elements directly on screenshots.
"""

import asyncio
import base64
import io
import logging
import os

from PIL import Image, ImageDraw, ImageFont

from browser_use.dom.views import DOMSelectorMap, EnhancedDOMTreeNode
from browser_use.observability import observe_debug
from browser_use.utils import time_execution_async

logger = logging.getLogger(__name__)

# Font cache to prevent repeated font loading and reduce memory usage
_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont | None] = {}

# Cross-platform font paths
_FONT_PATHS = [
	'/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',  # Linux (Debian/Ubuntu)
	'/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',  # Linux (Arch/Fedora)
	'/System/Library/Fonts/Arial.ttf',  # macOS
	'C:\\Windows\\Fonts\\arial.ttf',  # Windows
	'arial.ttf',  # Windows (system path)
	'Arial Bold.ttf',  # macOS alternative
	'/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',  # Linux alternative
]


def get_cross_platform_font(font_size: int) -> ImageFont.FreeTypeFont | None:
	"""Get a cross-platform compatible font with caching to prevent memory leaks.

	Args:
	    font_size: Size of the font to load

	Returns:
	    ImageFont object or None if no system fonts are available
	"""
	# Use cache key based on font size
	cache_key = ('system_font', font_size)

	# Return cached font if available
	if cache_key in _FONT_CACHE:
		return _FONT_CACHE[cache_key]

	# Try to load a system font
	font = None
	for font_path in _FONT_PATHS:
		try:
			font = ImageFont.truetype(font_path, font_size)
			break
		except OSError:
			continue

	# Cache the result (even if None) to avoid repeated attempts
	_FONT_CACHE[cache_key] = font
	return font


def cleanup_font_cache() -> None:
	"""Clean up the font cache to prevent memory leaks in long-running applications."""
	global _FONT_CACHE
	_FONT_CACHE.clear()


# Color scheme for different element types
ELEMENT_COLORS = {
	'button': '#FF6B6B',  # Red for buttons
	'input': '#4ECDC4',  # Teal for inputs
	'select': '#45B7D1',  # Blue for dropdowns
	'a': '#96CEB4',  # Green for links
	'textarea': '#FF8C42',  # Orange for text areas (was yellow, now more visible)
	'default': '#DDA0DD',  # Light purple for other interactive elements
}

# Element type mappings
ELEMENT_TYPE_MAP = {
	'button': 'button',
	'input': 'input',
	'select': 'select',
	'a': 'a',
	'textarea': 'textarea',
}


def get_element_color(tag_name: str, element_type: str | None = None) -> str:
	"""Get color for element based on tag name and type."""
	# Check input type first
	if tag_name == 'input' and element_type:
		if element_type in ['button', 'submit']:
			return ELEMENT_COLORS['button']

	# Use tag-based color
	return ELEMENT_COLORS.get(tag_name.lower(), ELEMENT_COLORS['default'])


def should_show_index_overlay(backend_node_id: int | None) -> bool:
	"""Determine if index overlay should be shown."""
	return backend_node_id is not None


def _clamp_overlay_box(
	box: tuple[int, int, int, int], image_size: tuple[int, int]
) -> tuple[int, int, int, int]:
	"""Clamp an overlay box so it remains fully visible within the screenshot bounds."""
	img_width, img_height = image_size
	x1, y1, x2, y2 = box
	box_width = x2 - x1
	box_height = y2 - y1

	max_x1 = max(0, img_width - box_width)
	max_y1 = max(0, img_height - box_height)
	x1 = max(0, min(x1, max_x1))
	y1 = max(0, min(y1, max_y1))
	return (x1, y1, x1 + box_width, y1 + box_height)


def _boxes_overlap(
	box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int], margin: int = 4
) -> bool:
	"""Return True when two overlay boxes overlap or visually crowd each other."""
	return not (
		box_a[2] + margin <= box_b[0]
		or box_b[2] + margin <= box_a[0]
		or box_a[3] + margin <= box_b[1]
		or box_b[3] + margin <= box_a[1]
	)


def get_index_overlay_box(
	element_bbox: tuple[int, int, int, int],
	overlay_size: tuple[int, int],
	image_size: tuple[int, int],
	occupied_boxes: list[tuple[int, int, int, int]] | None = None,
) -> tuple[int, int, int, int]:
	"""Choose a readable overlay position that avoids colliding with earlier badges."""
	x1, y1, x2, y2 = element_bbox
	overlay_width, overlay_height = overlay_size
	element_width = x2 - x1
	element_height = y2 - y1
	small_element = element_width < 60 or element_height < 30
	gap = 5

	def candidate_box(left: int, top: int) -> tuple[int, int, int, int]:
		return _clamp_overlay_box((left, top, left + overlay_width, top + overlay_height), image_size)

	candidates = []
	if small_element:
		candidates.extend(
			[
				candidate_box(x1 + (element_width - overlay_width) // 2, y1 - overlay_height - gap),
				candidate_box(x1 + (element_width - overlay_width) // 2, y2 + gap),
				candidate_box(x2 + gap, y1 + (element_height - overlay_height) // 2),
				candidate_box(x1 - overlay_width - gap, y1 + (element_height - overlay_height) // 2),
				candidate_box(x1 + 2, y1 + 2),
			]
		)
	else:
		candidates.extend(
			[
				candidate_box(x1 + (element_width - overlay_width) // 2, y1 + 2),
				candidate_box(x1 + (element_width - overlay_width) // 2, y1 - overlay_height - gap),
				candidate_box(x2 + gap, y1 + 2),
				candidate_box(x1 - overlay_width - gap, y1 + 2),
				candidate_box(x1 + (element_width - overlay_width) // 2, y2 - overlay_height - 2),
			]
		)

	if occupied_boxes:
		for box in candidates:
			if not any(_boxes_overlap(box, occupied) for occupied in occupied_boxes):
				return box
		# As a fallback, keep nudging the preferred position until a clear spot is found.
		preferred_left, preferred_top = candidates[0][0], candidates[0][1]
		fallback_steps = [
			(0, overlay_height + gap),
			(0, -(overlay_height + gap)),
			(overlay_width + gap, 0),
			(-(overlay_width + gap), 0),
		]
		for dx, dy in fallback_steps:
			for step in range(1, 5):
				box = candidate_box(preferred_left + dx * step, preferred_top + dy * step)
				if not any(_boxes_overlap(box, occupied) for occupied in occupied_boxes):
					return box

	return candidates[0]


def draw_enhanced_bounding_box_with_text(
	draw,  # ImageDraw.Draw - avoiding type annotation due to PIL typing issues
	bbox: tuple[int, int, int, int],
	color: str,
	text: str | None = None,
	font: ImageFont.FreeTypeFont | None = None,
	element_type: str = 'div',
	image_size: tuple[int, int] = (2000, 1500),
	device_pixel_ratio: float = 1.0,
	occupied_label_boxes: list[tuple[int, int, int, int]] | None = None,
) -> None:
	"""Draw an enhanced bounding box with much bigger index containers and dashed borders."""
	x1, y1, x2, y2 = bbox

	# Draw dashed bounding box with pattern: 1 line, 2 spaces, 1 line, 2 spaces...
	dash_length = 4
	gap_length = 8
	line_width = 2

	# Helper function to draw dashed line
	def draw_dashed_line(start_x, start_y, end_x, end_y):
		if start_x == end_x:  # Vertical line
			y = start_y
			while y < end_y:
				dash_end = min(y + dash_length, end_y)
				draw.line([(start_x, y), (start_x, dash_end)], fill=color, width=line_width)
				y += dash_length + gap_length
		else:  # Horizontal line
			x = start_x
			while x < end_x:
				dash_end = min(x + dash_length, end_x)
				draw.line([(x, start_y), (dash_end, start_y)], fill=color, width=line_width)
				x += dash_length + gap_length

	# Draw dashed rectangle
	draw_dashed_line(x1, y1, x2, y1)  # Top
	draw_dashed_line(x2, y1, x2, y2)  # Right
	draw_dashed_line(x2, y2, x1, y2)  # Bottom
	draw_dashed_line(x1, y2, x1, y1)  # Left

	# Draw much bigger index overlay if we have index text
	if text:
		try:
			css_width = image_size[0]
			base_font_size = max(10, min(20, int(css_width * 0.01)))
			big_font = get_cross_platform_font(base_font_size)
			if big_font is None:
				big_font = font

			if big_font:
				bbox_text = draw.textbbox((0, 0), text, font=big_font)
				text_width = bbox_text[2] - bbox_text[0]
				text_height = bbox_text[3] - bbox_text[1]
			else:
				bbox_text = draw.textbbox((0, 0), text)
				text_width = bbox_text[2] - bbox_text[0]
				text_height = bbox_text[3] - bbox_text[1]

			padding = max(4, min(10, int(css_width * 0.005)))
			container_width = text_width + padding * 2
			container_height = text_height + padding * 2
			bg_x1, bg_y1, bg_x2, bg_y2 = get_index_overlay_box(
				(x1, y1, x2, y2),
				(container_width, container_height),
				image_size,
				occupied_boxes=occupied_label_boxes,
			)

			text_x = bg_x1 + (container_width - text_width) // 2
			text_y = bg_y1 + (container_height - text_height) // 2 - bbox_text[1]

			draw.rectangle([bg_x1, bg_y1, bg_x2, bg_y2], fill=color, outline='white', width=2)
			draw.text((text_x, text_y), text, fill='white', font=big_font or font)

			if occupied_label_boxes is not None:
				occupied_label_boxes.append((bg_x1, bg_y1, bg_x2, bg_y2))

		except Exception as e:
			logger.debug(f'Failed to draw enhanced text overlay: {e}')


def draw_bounding_box_with_text(
	draw,  # ImageDraw.Draw - avoiding type annotation due to PIL typing issues
	bbox: tuple[int, int, int, int],
	color: str,
	text: str | None = None,
	font: ImageFont.FreeTypeFont | None = None,
) -> None:
	"""Draw a bounding box with optional text overlay."""
	x1, y1, x2, y2 = bbox

	# Draw dashed bounding box
	dash_length = 2
	gap_length = 6

	# Top edge
	x = x1
	while x < x2:
		end_x = min(x + dash_length, x2)
		draw.line([(x, y1), (end_x, y1)], fill=color, width=2)
		draw.line([(x, y1 + 1), (end_x, y1 + 1)], fill=color, width=2)
		x += dash_length + gap_length

	# Bottom edge
	x = x1
	while x < x2:
		end_x = min(x + dash_length, x2)
		draw.line([(x, y2), (end_x, y2)], fill=color, width=2)
		draw.line([(x, y2 - 1), (end_x, y2 - 1)], fill=color, width=2)
		x += dash_length + gap_length

	# Left edge
	y = y1
	while y < y2:
		end_y = min(y + dash_length, y2)
		draw.line([(x1, y), (x1, end_y)], fill=color, width=2)
		draw.line([(x1 + 1, y), (x1 + 1, end_y)], fill=color, width=2)
		y += dash_length + gap_length

	# Right edge
	y = y1
	while y < y2:
		end_y = min(y + dash_length, y2)
		draw.line([(x2, y), (x2, end_y)], fill=color, width=2)
		draw.line([(x2 - 1, y), (x2 - 1, end_y)], fill=color, width=2)
		y += dash_length + gap_length

	# Draw index overlay if we have index text
	if text:
		try:
			# Get text size
			if font:
				bbox_text = draw.textbbox((0, 0), text, font=font)
				text_width = bbox_text[2] - bbox_text[0]
				text_height = bbox_text[3] - bbox_text[1]
			else:
				# Fallback for default font
				bbox_text = draw.textbbox((0, 0), text)
				text_width = bbox_text[2] - bbox_text[0]
				text_height = bbox_text[3] - bbox_text[1]

			# Smart positioning based on element size
			padding = 5
			element_width = x2 - x1
			element_height = y2 - y1
			element_area = element_width * element_height
			index_box_area = (text_width + padding * 2) * (text_height + padding * 2)

			# Calculate size ratio to determine positioning strategy
			size_ratio = element_area / max(index_box_area, 1)

			if size_ratio < 4:
				# Very small elements: place outside in bottom-right corner
				text_x = x2 + padding
				text_y = y2 - text_height
				# Ensure it doesn't go off screen
				text_x = min(text_x, 1200 - text_width - padding)
				text_y = max(text_y, 0)
			elif size_ratio < 16:
				# Medium elements: place in bottom-right corner inside
				text_x = x2 - text_width - padding
				text_y = y2 - text_height - padding
			else:
				# Large elements: place in center
				text_x = x1 + (element_width - text_width) // 2
				text_y = y1 + (element_height - text_height) // 2

			# Ensure text stays within bounds
			text_x = max(0, min(text_x, 1200 - text_width))
			text_y = max(0, min(text_y, 800 - text_height))

			# Draw background rectangle for maximum contrast
			bg_x1 = text_x - padding
			bg_y1 = text_y - padding
			bg_x2 = text_x + text_width + padding
			bg_y2 = text_y + text_height + padding

			# Use white background with thick black border for maximum visibility
			draw.rectangle([bg_x1, bg_y1, bg_x2, bg_y2], fill='white', outline='black', width=2)

			# Draw bold dark text on light background for best contrast
			draw.text((text_x, text_y), text, fill='black', font=font)

		except Exception as e:
			logger.debug(f'Failed to draw text overlay: {e}')


def process_element_highlight(
	element_id: int,
	element: EnhancedDOMTreeNode,
	draw,
	device_pixel_ratio: float,
	font,
	filter_highlight_ids: bool,
	image_size: tuple[int, int],
	occupied_label_boxes: list[tuple[int, int, int, int]] | None = None,
) -> None:
	"""Process a single element for highlighting."""
	try:
		# Use absolute_position coordinates directly
		if not element.absolute_position:
			return

		bounds = element.absolute_position

		# Scale coordinates from CSS pixels to device pixels for screenshot
		# The screenshot is captured at device pixel resolution, but coordinates are in CSS pixels
		x1 = int(bounds.x * device_pixel_ratio)
		y1 = int(bounds.y * device_pixel_ratio)
		x2 = int((bounds.x + bounds.width) * device_pixel_ratio)
		y2 = int((bounds.y + bounds.height) * device_pixel_ratio)

		# Ensure coordinates are within image bounds
		img_width, img_height = image_size
		x1 = max(0, min(x1, img_width))
		y1 = max(0, min(y1, img_height))
		x2 = max(x1, min(x2, img_width))
		y2 = max(y1, min(y2, img_height))

		# Skip if bounding box is too small or invalid
		if x2 - x1 < 2 or y2 - y1 < 2:
			return

		# Get element color based on type
		tag_name = element.tag_name if hasattr(element, 'tag_name') else 'div'
		element_type = None
		if hasattr(element, 'attributes') and element.attributes:
			element_type = element.attributes.get('type')

		color = get_element_color(tag_name, element_type)

		# Get element index for overlay and apply filtering
		backend_node_id = getattr(element, 'backend_node_id', None)
		index_text = None

		if backend_node_id is not None:
			if filter_highlight_ids:
				# Use the meaningful text that matches what the LLM sees
				meaningful_text = element.get_meaningful_text_for_llm()
				# Show ID only if meaningful text is less than 5 characters
				if len(meaningful_text) < 3:
					index_text = str(backend_node_id)
			else:
				# Always show ID when filter is disabled
				index_text = str(backend_node_id)

		# Draw enhanced bounding box with bigger index
		draw_enhanced_bounding_box_with_text(
			draw,
			(x1, y1, x2, y2),
			color,
			index_text,
			font,
			tag_name,
			image_size,
			device_pixel_ratio,
			occupied_label_boxes,
		)

	except Exception as e:
		logger.debug(f'Failed to draw highlight for element {element_id}: {e}')


@observe_debug(ignore_input=True, ignore_output=True, name='create_highlighted_screenshot')
@time_execution_async('create_highlighted_screenshot')
async def create_highlighted_screenshot(
	screenshot_b64: str,
	selector_map: DOMSelectorMap,
	device_pixel_ratio: float = 1.0,
	viewport_offset_x: int = 0,
	viewport_offset_y: int = 0,
	filter_highlight_ids: bool = True,
) -> str:
	"""Create a highlighted screenshot with bounding boxes around interactive elements.

	Args:
	    screenshot_b64: Base64 encoded screenshot
	    selector_map: Map of interactive elements with their positions
	    device_pixel_ratio: Device pixel ratio for scaling coordinates
	    viewport_offset_x: X offset for viewport positioning
	    viewport_offset_y: Y offset for viewport positioning

	Returns:
	    Base64 encoded highlighted screenshot
	"""
	try:
		# Decode screenshot
		screenshot_data = base64.b64decode(screenshot_b64)
		image = Image.open(io.BytesIO(screenshot_data)).convert('RGBA')

		# Create drawing context
		draw = ImageDraw.Draw(image)

		# Load font using shared function with caching
		font = get_cross_platform_font(12)
		# If no system fonts found, font remains None and will use default font

		# Process elements sequentially to avoid ImageDraw thread safety issues
		# PIL ImageDraw is not thread-safe, so we process elements one by one
		occupied_label_boxes: list[tuple[int, int, int, int]] = []
		for element_id, element in selector_map.items():
			process_element_highlight(
				element_id,
				element,
				draw,
				device_pixel_ratio,
				font,
				filter_highlight_ids,
				image.size,
				occupied_label_boxes,
			)

		# Convert back to base64
		output_buffer = io.BytesIO()
		try:
			image.save(output_buffer, format='PNG')
			output_buffer.seek(0)
			highlighted_b64 = base64.b64encode(output_buffer.getvalue()).decode('utf-8')

			logger.debug(f'Successfully created highlighted screenshot with {len(selector_map)} elements')
			return highlighted_b64
		finally:
			# Explicit cleanup to prevent memory leaks
			output_buffer.close()
			if 'image' in locals():
				image.close()

	except Exception as e:
		logger.error(f'Failed to create highlighted screenshot: {e}')
		# Clean up on error as well
		if 'image' in locals():
			image.close()
		# Return original screenshot on error
		return screenshot_b64


async def get_viewport_info_from_cdp(cdp_session) -> tuple[float, int, int]:
	"""Get viewport information from CDP session.

	Returns:
	    Tuple of (device_pixel_ratio, scroll_x, scroll_y)
	"""
	try:
		# Get layout metrics which includes viewport info and device pixel ratio
		metrics = await cdp_session.cdp_client.send.Page.getLayoutMetrics(session_id=cdp_session.session_id)

		# Extract viewport information
		visual_viewport = metrics.get('visualViewport', {})
		css_visual_viewport = metrics.get('cssVisualViewport', {})
		css_layout_viewport = metrics.get('cssLayoutViewport', {})

		# Calculate device pixel ratio
		css_width = css_visual_viewport.get('clientWidth', css_layout_viewport.get('clientWidth', 1280.0))
		device_width = visual_viewport.get('clientWidth', css_width)
		device_pixel_ratio = device_width / css_width if css_width > 0 else 1.0

		# Get scroll position in CSS pixels
		scroll_x = int(css_visual_viewport.get('pageX', 0))
		scroll_y = int(css_visual_viewport.get('pageY', 0))

		return float(device_pixel_ratio), scroll_x, scroll_y

	except Exception as e:
		logger.debug(f'Failed to get viewport info from CDP: {e}')
		return 1.0, 0, 0


@time_execution_async('create_highlighted_screenshot_async')
async def create_highlighted_screenshot_async(
	screenshot_b64: str, selector_map: DOMSelectorMap, cdp_session=None, filter_highlight_ids: bool = True
) -> str:
	"""Async wrapper for creating highlighted screenshots.

	Args:
	    screenshot_b64: Base64 encoded screenshot
	    selector_map: Map of interactive elements
	    cdp_session: CDP session for getting viewport info
	    filter_highlight_ids: Whether to filter element IDs based on meaningful text

	Returns:
	    Base64 encoded highlighted screenshot
	"""
	# Get viewport information if CDP session is available
	device_pixel_ratio = 1.0
	viewport_offset_x = 0
	viewport_offset_y = 0

	if cdp_session:
		try:
			device_pixel_ratio, viewport_offset_x, viewport_offset_y = await get_viewport_info_from_cdp(cdp_session)
		except Exception as e:
			logger.debug(f'Failed to get viewport info from CDP: {e}')

	# Create highlighted screenshot with async processing
	final_screenshot = await create_highlighted_screenshot(
		screenshot_b64, selector_map, device_pixel_ratio, viewport_offset_x, viewport_offset_y, filter_highlight_ids
	)

	filename = os.getenv('BROWSER_USE_SCREENSHOT_FILE')
	if filename:

		def _write_screenshot():
			try:
				with open(filename, 'wb') as f:
					f.write(base64.b64decode(final_screenshot))
				logger.debug('Saved screenshot to ' + str(filename))
			except Exception as e:
				logger.warning(f'Failed to save screenshot to {filename}: {e}')

		await asyncio.to_thread(_write_screenshot)
	return final_screenshot


# Export the cleanup function for external use in long-running applications
__all__ = ['create_highlighted_screenshot', 'create_highlighted_screenshot_async', 'cleanup_font_cache']
