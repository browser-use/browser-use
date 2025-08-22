"""Python-based highlighting system for drawing bounding boxes on screenshots.

This module replaces JavaScript-based highlighting with fast Python image processing
to draw bounding boxes around interactive elements directly on screenshots.
"""

import base64
import io
import logging
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from browser_use.dom.views import DOMSelectorMap
from browser_use.observability import observe_debug

logger = logging.getLogger(__name__)

# Color scheme for different element types
ELEMENT_COLORS = {
	'button': '#FF6B6B',  # Red for buttons
	'input': '#4ECDC4',  # Teal for inputs
	'select': '#45B7D1',  # Blue for dropdowns
	'a': '#96CEB4',  # Green for links
	'textarea': '#FFEAA7',  # Yellow for text areas
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


def get_element_color(tag_name: str, element_type: Optional[str] = None) -> str:
	"""Get color for element based on tag name and type."""
	# Check input type first
	if tag_name == 'input' and element_type:
		if element_type in ['button', 'submit']:
			return ELEMENT_COLORS['button']

	# Use tag-based color
	return ELEMENT_COLORS.get(tag_name.lower(), ELEMENT_COLORS['default'])


def should_show_index_overlay(element_index: Optional[int]) -> bool:
	"""Determine if index overlay should be shown."""
	return element_index is not None


def draw_bounding_box_with_text(
	draw,  # ImageDraw.Draw - avoiding type annotation due to PIL typing issues
	bbox: Tuple[int, int, int, int],
	color: str,
	text: Optional[str] = None,
	font: Optional[ImageFont.FreeTypeFont] = None,
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
			padding = 3
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


@observe_debug(ignore_input=True, ignore_output=True, name='create_highlighted_screenshot')
def create_highlighted_screenshot(
	screenshot_b64: str,
	selector_map: DOMSelectorMap,
	device_pixel_ratio: float = 1.0,
	viewport_offset_x: int = 0,
	viewport_offset_y: int = 0,
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

		# Try to load a font, fall back to default if not available
		font = None
		try:
			font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 12)
		except (OSError, IOError):
			try:
				font = ImageFont.truetype('arial.ttf', 12)
			except (OSError, IOError):
				font = None  # Use default font

		# Process each interactive element
		for element_id, element in selector_map.items():
			try:
				# Use snapshot bounds (document coordinates) if available, otherwise absolute_position
				bounds = None
				if element.snapshot_node and element.snapshot_node.bounds:
					bounds = element.snapshot_node.bounds
				elif element.absolute_position:
					bounds = element.absolute_position

				if not bounds:
					continue

				# Convert from CSS pixels to device pixels for screenshot coordinates
				# Note: bounds are already in CSS pixels, screenshot is in device pixels
				x1 = int((bounds.x - viewport_offset_x) * device_pixel_ratio)
				y1 = int((bounds.y - viewport_offset_y) * device_pixel_ratio)
				x2 = int((bounds.x + bounds.width - viewport_offset_x) * device_pixel_ratio)
				y2 = int((bounds.y + bounds.height - viewport_offset_y) * device_pixel_ratio)

				# Ensure coordinates are within image bounds
				img_width, img_height = image.size
				x1 = max(0, min(x1, img_width))
				y1 = max(0, min(y1, img_height))
				x2 = max(x1, min(x2, img_width))
				y2 = max(y1, min(y2, img_height))

				# Skip if bounding box is too small or invalid
				if x2 - x1 < 2 or y2 - y1 < 2:
					continue

				# Get element color based on type
				tag_name = element.tag_name if hasattr(element, 'tag_name') else 'div'
				element_type = None
				if hasattr(element, 'attributes') and element.attributes:
					element_type = element.attributes.get('type')

				color = get_element_color(tag_name, element_type)

				# Get element index for overlay
				element_index = getattr(element, 'element_index', None)
				index_text = str(element_index) if element_index is not None else None

				# Draw bounding box with index
				draw_bounding_box_with_text(draw, (x1, y1, x2, y2), color, index_text, font)

			except Exception as e:
				logger.debug(f'Failed to draw highlight for element {element_id}: {e}')
				continue

		# Convert back to base64
		output_buffer = io.BytesIO()
		image.save(output_buffer, format='PNG')
		output_buffer.seek(0)

		highlighted_b64 = base64.b64encode(output_buffer.getvalue()).decode('utf-8')

		logger.debug(f'Successfully created highlighted screenshot with {len(selector_map)} elements')
		return highlighted_b64

	except Exception as e:
		logger.error(f'Failed to create highlighted screenshot: {e}')
		# Return original screenshot on error
		return screenshot_b64


async def get_viewport_info_from_cdp(cdp_session) -> Tuple[float, int, int]:
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


@observe_debug(ignore_input=True, ignore_output=True, name='create_highlighted_screenshot_async')
async def create_highlighted_screenshot_async(screenshot_b64: str, selector_map: DOMSelectorMap, cdp_session=None) -> str:
	"""Async wrapper for creating highlighted screenshots.

	Args:
	    screenshot_b64: Base64 encoded screenshot
	    selector_map: Map of interactive elements
	    cdp_session: CDP session for getting viewport info

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

	# Create highlighted screenshot (run in thread pool if needed for performance)
	return create_highlighted_screenshot(screenshot_b64, selector_map, device_pixel_ratio, viewport_offset_x, viewport_offset_y)
