"""
Hybrid extraction approach combining DOM-based and OmniParser based UI element extraction.
"""

import base64
import logging
from typing import Optional

from browser_use.dom.service import DomService
from browser_use.dom.views import DOMState
from browser_use.omniparser.captcha import CaptchaDetector
from browser_use.omniparser.service import OmniParserService
from browser_use.omniparser.views import OmniParserSettings

logger = logging.getLogger(__name__)


class HybridExtractor:
    """
    Combines DOM-based extraction with OmniParser vision-based extraction.
    This provides a more robust element detection, especially for complex UI scenarios.
    """
    
    def __init__(self, dom_service: DomService, settings: Optional[OmniParserSettings] = None):
        """
        Initialize the hybrid extractor.
        
        Args:
            dom_service: DOM service for regular extraction
            settings: Optional settings for OmniParser integration
        """
        self.dom_service = dom_service
        self.settings = settings or OmniParserSettings()
        self.omniparser = OmniParserService(
            weights_dir=self.settings.weights_dir,
            api_key=self.settings.api_key,
            use_api=self.settings.use_api
        )
        
        # Initialize CAPTCHA detector if setting enabled
        self.captcha_detector = None
        if self.settings.captcha_detection:
            self.captcha_detector = CaptchaDetector(self.omniparser, self.settings)
    
    async def get_elements(self, highlight_elements: bool = True, focus_element: int = -1, 
                          viewport_expansion: int = 500) -> DOMState:
        """
        Get UI elements using the hybrid approach.
        
        Args:
            highlight_elements: Whether to highlight elements in the browser
            focus_element: Index of element to focus on
            viewport_expansion: Pixels to expand viewport by for element detection
            
        Returns:
            DOM state with detected elements
        """
        # First get DOM-based elements
        dom_state = await self.dom_service.get_clickable_elements(
            highlight_elements=highlight_elements,
            focus_element=focus_element,
            viewport_expansion=viewport_expansion
        )
        
        # Skip OmniParser if disabled
        if not self.settings.enabled:
            return dom_state
            
        try:
            # Take a screenshot for OmniParser
            page = self.dom_service.page
            screenshot = await page.screenshot(type="png", full_page=False)
            screenshot_b64 = base64.b64encode(screenshot).decode("utf-8")
            
            # If CAPTCHA detection is enabled, use that specialized flow
            if self.settings.captcha_detection and self.captcha_detector:
                captcha_elements = await self.captcha_detector.detect_captchas(screenshot_b64)
                
                if captcha_elements:
                    logger.info(f"Detected {len(captcha_elements)} potential CAPTCHA elements")
                    enhanced_dom = self.captcha_detector.enhance_dom_with_captchas(dom_state, captcha_elements)
                    return enhanced_dom
            
            # If we should completely replace DOM results with OmniParser
            if self.settings.prefer_over_dom:
                omni_elements = await self.omniparser.create_dom_state_from_screenshot(screenshot_b64)
                if omni_elements and omni_elements.element_tree and len(omni_elements.selector_map or {}) > 0:
                    logger.info("Using OmniParser results instead of DOM-based extraction")
                    return omni_elements
            
            # If we should merge results
            if self.settings.merge_with_dom:
                omni_elements = await self.omniparser.detect_interactive_elements(screenshot_b64)
                if omni_elements:
                    logger.info(f"Merging {len(omni_elements)} OmniParser elements with DOM results")
                    enhanced_dom = self._merge_with_dom(dom_state, omni_elements)
                    return enhanced_dom
            
            # Default - return DOM state
            return dom_state
                
        except Exception as e:
            logger.error(f"Error in hybrid extraction, falling back to DOM-based: {str(e)}")
            return dom_state
    
    def _merge_with_dom(self, dom_state: DOMState, omni_elements: list) -> DOMState:
        """
        Merge OmniParser elements with DOM-based elements.
        
        Args:
            dom_state: Current DOM state from DOM-based extraction
            omni_elements: Elements detected by OmniParser
            
        Returns:
            Enhanced DOM state with merged elements
        """
        # Import needed for making copies
        from copy import deepcopy
        
        # Create a deep copy to avoid modifying the original
        new_dom = deepcopy(dom_state)
        
        # Function to check if a given OmniParser element overlaps with any DOM element
        def element_overlaps_with_dom(omni_element, dom_element):
            if not dom_element:
                return False
            
            # Get positions from either page_coordinates or viewport_coordinates
            dom_box = {}
            if hasattr(dom_element, 'page_coordinates') and dom_element.page_coordinates:
                dom_box = {
                    "x": dom_element.page_coordinates.top_left.x,
                    "y": dom_element.page_coordinates.top_left.y,
                    "width": dom_element.page_coordinates.width,
                    "height": dom_element.page_coordinates.height
                }
            elif hasattr(dom_element, 'viewport_coordinates') and dom_element.viewport_coordinates:
                dom_box = {
                    "x": dom_element.viewport_coordinates.top_left.x,
                    "y": dom_element.viewport_coordinates.top_left.y,
                    "width": dom_element.viewport_coordinates.width,
                    "height": dom_element.viewport_coordinates.height
                }
            elif hasattr(dom_element, 'x') and hasattr(dom_element, 'y'):
                dom_box = {
                    "x": dom_element.x,
                    "y": dom_element.y,
                    "width": dom_element.width,
                    "height": dom_element.height
                }
            else:
                # No coordinate information available
                return False
        
            omni_box = {
                "x": omni_element.get("x", 0),
                "y": omni_element.get("y", 0),
                "width": omni_element.get("width", 0),
                "height": omni_element.get("height", 0)
            }
        
            # Check for intersection
            no_overlap = (
                dom_box["x"] + dom_box["width"] < omni_box["x"] or
                omni_box["x"] + omni_box["width"] < dom_box["x"] or
                dom_box["y"] + dom_box["height"] < omni_box["y"] or
                omni_box["y"] + omni_box["height"] < dom_box["y"]
            )
        
            return not no_overlap
        
        # Check if element or its children overlap with an OmniParser element
        def check_element_tree(element, overlapped_elements):
            if not element:
                return
            
            for omni_element in omni_elements:
                if element_overlaps_with_dom(omni_element, element):
                    # Add OmniParser data to the element
                    if not hasattr(element, 'attributes') or element.attributes is None:
                        element.attributes = {}
                    element.attributes["data-omniparser-detected"] = "true"
                    element.attributes["data-omniparser-type"] = omni_element.get("element_type", "unknown")
                    element.attributes["data-omniparser-confidence"] = str(omni_element.get("confidence", 0.0))
                    
                    # Update text if OmniParser found text and current element has none
                    if not element.text and omni_element.get("text"):
                        element.text = omni_element.get("text")
                    
                    overlapped_elements.add(id(omni_element))  # Use id() since dicts aren't hashable
        
            # Recursively check children
            if hasattr(element, 'children') and element.children:
                for child in element.children:
                    check_element_tree(child, overlapped_elements)
        
        # Track which OmniParser elements overlap with DOM elements
        overlapped_elements = set()
        
        # Start the recursive check
        if new_dom.element_tree:
            check_element_tree(new_dom.element_tree, overlapped_elements)
        
        # Add any non-overlapping OmniParser elements as new DOM elements
        for i, omni_element in enumerate(omni_elements):
            if id(omni_element) in overlapped_elements:
                continue
                
            # Create a new DOM element for this OmniParser element
            from browser_use.dom.views import DOMElementNode
            from browser_use.dom.history_tree_processor.view import CoordinateSet, Coordinates
            
            x = omni_element.get("x", 0)
            y = omni_element.get("y", 0)
            width = omni_element.get("width", 0)
            height = omni_element.get("height", 0)
            
            # Create coordinate sets for the element with all required fields
            page_coordinates = CoordinateSet(
                top_left=Coordinates(x=x, y=y),
                top_right=Coordinates(x=x + width, y=y),
                bottom_left=Coordinates(x=x, y=y + height),
                bottom_right=Coordinates(x=x + width, y=y + height),
                center=Coordinates(x=x + width // 2, y=y + height // 2),
                width=width,
                height=height
            )
            
            # Use the same coordinates for viewport (simplified)
            viewport_coordinates = CoordinateSet(
                top_left=Coordinates(x=x, y=y),
                top_right=Coordinates(x=x + width, y=y),
                bottom_left=Coordinates(x=x, y=y + height),
                bottom_right=Coordinates(x=x + width, y=y + height),
                center=Coordinates(x=x + width // 2, y=y + height // 2),
                width=width,
                height=height
            )
            
            new_element = DOMElementNode(
                tag_name="div",
                xpath=f"//div[@id='omniparser-{i}']",
                attributes={
                    "id": f"omniparser-{i}",
                    "class": "omniparser-element",
                    "data-omniparser-detected": "true",
                    "data-omniparser-type": omni_element.get("element_type", "unknown"),
                    "data-omniparser-confidence": str(omni_element.get("confidence", 0.0))
                },
                children=[],
                is_visible=True,
                is_interactive=True,
                is_top_element=True,
                is_in_viewport=True,
                highlight_index=len(new_dom.selector_map) + i if new_dom.selector_map else i,
                shadow_root=False,
                parent=None,
                page_coordinates=page_coordinates,
                viewport_coordinates=viewport_coordinates
            )
            
            # Add to tree (as a child of body if no existing tree)
            if not new_dom.element_tree:
                # Create minimal tree
                from browser_use.dom.history_tree_processor.view import CoordinateSet, Coordinates
                
                # Default viewport size
                width = 1280
                height = 1024
                
                # Create coordinate sets for the body
                page_coordinates = CoordinateSet(
                    top_left=Coordinates(x=0, y=0),
                    top_right=Coordinates(x=width, y=0),
                    bottom_left=Coordinates(x=0, y=height),
                    bottom_right=Coordinates(x=width, y=height),
                    center=Coordinates(x=width // 2, y=height // 2),
                    width=width,
                    height=height
                )
                
                # Use the same coordinates for viewport
                viewport_coordinates = CoordinateSet(
                    top_left=Coordinates(x=0, y=0),
                    top_right=Coordinates(x=width, y=0),
                    bottom_left=Coordinates(x=0, y=height),
                    bottom_right=Coordinates(x=width, y=height),
                    center=Coordinates(x=width // 2, y=height // 2),
                    width=width,
                    height=height
                )
                
                body = DOMElementNode(
                    tag_name="body",
                    xpath="/body",
                    attributes={},
                    children=[],
                    is_visible=True,
                    is_interactive=False,
                    is_top_element=True,
                    is_in_viewport=True,
                    highlight_index=0,
                    shadow_root=False,
                    parent=None,
                    page_coordinates=page_coordinates,
                    viewport_coordinates=viewport_coordinates
                )
                # Add the new element as a child
                body.children = [new_element]
                new_element.parent = body
                new_dom.element_tree = body
            else:
                # Add to existing tree
                if not new_dom.element_tree.children:
                    new_dom.element_tree.children = []
                new_dom.element_tree.children.append(new_element)
                new_element.parent = new_dom.element_tree
            
            # Update selector map
            if new_dom.selector_map is None:
                new_dom.selector_map = {}
            new_dom.selector_map[new_element.highlight_index] = new_element.xpath
        
        return new_dom
