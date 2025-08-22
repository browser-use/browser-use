"""
Python-based highlighting system for interactive elements.

This module provides fast Python-based highlighting of interactive elements
without requiring browser scripts injection. It takes screenshots and element
coordinates to create highlighted images with color-coded bounding boxes.

@file purpose: Defines Python-based highlighting for interactive elements
"""

import base64
from io import BytesIO
from typing import Dict, List, Optional, Set

from PIL import Image, ImageDraw, ImageFont

from browser_use.dom.views import DOMSelectorMap


# Color mapping for different element types
ELEMENT_COLORS = {
    'button': '#FF6B6B',      # Red
    'input': '#4ECDC4',       # Teal  
    'select': '#45B7D1',      # Blue
    'textarea': '#96CEB4',    # Green
    'a': '#FFEAA7',           # Yellow
    'link': '#FFEAA7',        # Yellow (same as 'a')
    'checkbox': '#DDA0DD',    # Plum
    'radio': '#F39C12',       # Orange
    'file': '#9B59B6',        # Purple
    'submit': '#E74C3C',      # Dark Red
    'dropdown': '#3498DB',    # Dodger Blue
    'default': '#74B9FF',     # Light Blue
}


def get_element_type(node) -> str:
    """Determine the element type for color coding."""
    if not node.tag_name:
        return 'default'
    
    tag = node.tag_name.lower()
    
    # Direct tag mapping
    if tag in ['button', 'select', 'textarea', 'a']:
        return tag
    
    # Input element type detection
    if tag == 'input':
        input_type = node.attributes.get('type', '').lower() if node.attributes else ''
        if input_type in ['checkbox', 'radio', 'file', 'submit']:
            return input_type
        return 'input'
    
    # Link detection
    if tag == 'a' or (node.attributes and node.attributes.get('href')):
        return 'link'
    
    # Dropdown detection (select or role=combobox)
    if tag == 'select' or (node.attributes and node.attributes.get('role') == 'combobox'):
        return 'dropdown'
    
    return 'default'


def create_highlighted_image(
    screenshot_b64: str,
    selector_map: DOMSelectorMap,
    include_indices: Optional[Set[int]] = None,
    exclude_indices: Optional[Set[int]] = None,
    show_index_labels: bool = True,
    box_thickness: int = 2,
) -> str:
    """
    Create a highlighted image with bounding boxes around interactive elements.
    
    Args:
        screenshot_b64: Base64 encoded screenshot
        selector_map: Dictionary mapping element indices to DOM nodes
        include_indices: Set of indices to include (if None, include all)
        exclude_indices: Set of indices to exclude
        show_index_labels: Whether to show index numbers on boxes
        box_thickness: Thickness of bounding box outlines
        
    Returns:
        Base64 encoded highlighted image
    """
    # Decode the screenshot
    image_data = base64.b64decode(screenshot_b64)
    image = Image.open(BytesIO(image_data))
    
    # Create a copy for drawing
    highlighted_image = image.copy()
    draw = ImageDraw.Draw(highlighted_image)
    
    # Try to load a font for labels (fall back to default if not available)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 12)  # macOS
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)  # Linux
            except (OSError, IOError):
                font = ImageFont.load_default()
    
    # Process each interactive element
    for interactive_index, node in selector_map.items():
        # Apply include/exclude filters
        if include_indices is not None and interactive_index not in include_indices:
            continue
        if exclude_indices is not None and interactive_index in exclude_indices:
            continue
            
        # Get element bounding box
        if not node.absolute_position:
            continue
            
        rect = node.absolute_position
        x, y = int(rect.x), int(rect.y)
        width, height = int(rect.width), int(rect.height)
        
        # Skip elements with invalid dimensions
        if width <= 0 or height <= 0:
            continue
            
        # Get color based on element type
        element_type = get_element_type(node)
        color = ELEMENT_COLORS.get(element_type, ELEMENT_COLORS['default'])
        
        # Draw bounding box
        x2, y2 = x + width, y + height
        for i in range(box_thickness):
            draw.rectangle(
                [x - i, y - i, x2 + i, y2 + i],
                outline=color,
                fill=None
            )
        
        # Draw index label if requested
        if show_index_labels:
            label_text = str(interactive_index)
            
            # Calculate label position (top-left, slightly offset)
            label_x = max(0, x - 2)
            label_y = max(0, y - 20)
            
            # Get text bounding box for background
            bbox = draw.textbbox((label_x, label_y), label_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            # Draw label background
            draw.rectangle(
                [label_x - 2, label_y - 2, label_x + text_width + 2, label_y + text_height + 2],
                fill=color,
                outline=None
            )
            
            # Draw label text
            draw.text((label_x, label_y), label_text, fill='white', font=font)
    
    # Convert back to base64
    output_buffer = BytesIO()
    highlighted_image.save(output_buffer, format='PNG')
    output_buffer.seek(0)
    
    return base64.b64encode(output_buffer.getvalue()).decode('utf-8')


def convert_dom_elements_for_highlighting(selector_map: DOMSelectorMap) -> List[Dict]:
    """
    Convert DOMSelectorMap to a list of element info for highlighting.
    This is for compatibility and debugging purposes.
    
    Returns:
        List of element dictionaries with position and type info
    """
    elements = []
    
    for interactive_index, node in selector_map.items():
        if not node.absolute_position:
            continue
            
        rect = node.absolute_position
        if rect.width <= 0 or rect.height <= 0:
            continue
            
        element = {
            'index': interactive_index,
            'x': int(rect.x),
            'y': int(rect.y), 
            'width': int(rect.width),
            'height': int(rect.height),
            'type': get_element_type(node),
            'tag_name': node.tag_name,
            'text_content': (
                node.get_all_children_text()[:50] 
                if hasattr(node, 'get_all_children_text') 
                else str(node.node_value)[:50] if node.node_value else ''
            ),
            'attributes': node.attributes or {},
        }
        elements.append(element)
    
    return elements


def create_image_pair(
    screenshot_b64: str,
    selector_map: DOMSelectorMap,
    include_indices: Optional[Set[int]] = None,
    exclude_indices: Optional[Set[int]] = None,
) -> tuple[str, str]:
    """
    Create a pair of images: one without highlights and one with highlights.
    
    This is optimized for the use case where you want both versions quickly
    for merging or comparison.
    
    Args:
        screenshot_b64: Base64 encoded screenshot
        selector_map: Dictionary mapping element indices to DOM nodes
        include_indices: Set of indices to include (if None, include all)
        exclude_indices: Set of indices to exclude
        
    Returns:
        Tuple of (unhighlighted_b64, highlighted_b64)
    """
    # Original screenshot (unhighlighted)
    unhighlighted = screenshot_b64
    
    # Create highlighted version
    highlighted = create_highlighted_image(
        screenshot_b64=screenshot_b64,
        selector_map=selector_map,
        include_indices=include_indices,
        exclude_indices=exclude_indices,
        show_index_labels=True,
        box_thickness=2,
    )
    
    return unhighlighted, highlighted


def get_element_summary(selector_map: DOMSelectorMap) -> Dict:
    """
    Get a summary of elements by type for debugging/statistics.
    
    Returns:
        Dictionary with element counts by type
    """
    type_counts = {}
    
    for node in selector_map.values():
        element_type = get_element_type(node)
        type_counts[element_type] = type_counts.get(element_type, 0) + 1
    
    return {
        'total_elements': len(selector_map),
        'by_type': type_counts,
        'color_mapping': ELEMENT_COLORS,
    }