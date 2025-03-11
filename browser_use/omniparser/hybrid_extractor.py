"""
Hybrid extraction approach combining DOM-based and OmniParser based UI element extraction.
"""

import base64
import logging
from typing import Optional, Dict, Set, Any, Union, cast, List
from copy import deepcopy

from browser_use.dom.service import DomService
from browser_use.dom.views import DOMState, DOMElementNode, DOMBaseNode, DOMTextNode
from browser_use.omniparser.captcha import CaptchaDetector
from browser_use.omniparser.service import OmniParserService
from browser_use.omniparser.views import OmniParserSettings
from browser_use.dom.history_tree_processor.view import CoordinateSet, Coordinates

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
            endpoint=self.settings.endpoint,  # Use configured endpoint
            use_api=self.settings.use_api,
            api_key=self.settings.api_key  # Pass API key if configured
        )
        
        # Initialize CAPTCHA detector if setting enabled
        self.captcha_detector = None
        if self.settings.captcha_detection:
            self.captcha_detector = CaptchaDetector(self.omniparser, self.settings)
        
        # Cache for last screenshot to avoid reprocessing
        self._last_screenshot: Optional[str] = None
    
    def _is_dom_extraction_sufficient(self, dom_state: DOMState, required_elements: Optional[List[str]] = None) -> bool:
        """
        Evaluate if the DOM extraction provided sufficient results.
        
        Args:
            dom_state: The DOM state to evaluate
            required_elements: Optional list of required element types for LLM prediction
            
        Returns:
            bool: True if DOM extraction is sufficient, False otherwise
        """
        if not dom_state or not dom_state.selector_map:
            return False
            
        # Check if we have the minimum number of expected elements
        interactive_elements = [
            elem for elem in dom_state.selector_map.values() 
            if elem.is_interactive and elem.is_visible
        ]
        
        # If specific elements are required for LLM prediction
        if required_elements:
            # Check if all required element types are present
            found_types = set()
            for elem in interactive_elements:
                elem_type = elem.tag_name.lower()
                if 'type' in elem.attributes:
                    elem_type = elem.attributes['type'].lower()
                found_types.add(elem_type)
                
            # Return False if any required element type is missing
            if not all(req.lower() in found_types for req in required_elements):
                return False
        
        return len(interactive_elements) >= self.settings.min_expected_elements
    
    async def get_elements(self, highlight_elements: bool = True, focus_element: int = -1, 
                          viewport_expansion: int = 500, required_elements: Optional[List[str]] = None) -> DOMState:
        """
        Get UI elements using the hybrid approach.
        
        Args:
            highlight_elements: Whether to highlight elements in the browser
            focus_element: Index of element to focus on
            viewport_expansion: Pixels to expand viewport by for element detection
            required_elements: Optional list of required element types for LLM prediction
            
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
            
        # Check if we should use OmniParser
        should_use_omniparser = (
            not self.settings.use_as_fallback or  # Always use if not in fallback mode
            not self._is_dom_extraction_sufficient(dom_state, required_elements)  # Use as fallback if DOM insufficient
        )
        
        if not should_use_omniparser:
            logger.info("DOM extraction sufficient, skipping OmniParser")
            return dom_state
            
        try:
            # Take a screenshot for OmniParser
            page = self.dom_service.page
            screenshot = await page.screenshot(type="png", full_page=False)
            screenshot_b64 = base64.b64encode(screenshot).decode("utf-8")
            self._last_screenshot = screenshot_b64  # Cache screenshot
            
            # If CAPTCHA detection is enabled, use that specialized flow
            if self.settings.captcha_detection and self.captcha_detector:
                captcha_elements = await self.captcha_detector.detect_captchas(screenshot_b64)
                
                if captcha_elements:
                    logger.info(f"Detected {len(captcha_elements)} potential CAPTCHA elements")
                    enhanced_dom = self.captcha_detector.enhance_dom_with_captchas(dom_state, captcha_elements)
                    return enhanced_dom
            
            return await self._enhance_dom_state(dom_state, screenshot_b64)
                
        except Exception as e:
            logger.error(f"Error in hybrid extraction, falling back to DOM-based: {str(e)}")
            return dom_state

    async def find_specific_element(self, 
                                  dom_state: DOMState,
                                  element_type: Optional[str] = None,
                                  description_keywords: Optional[List[str]] = None,
                                  confidence_threshold: float = 0.5) -> Optional[DOMElementNode]:
        """
        Find a specific element using OmniParser when DOM extraction fails.
        
        Args:
            dom_state: Current DOM state
            element_type: Type of element to look for (e.g., "button", "input")
            description_keywords: Keywords to match in element descriptions
            confidence_threshold: Minimum confidence threshold
            
        Returns:
            Matching DOM element if found, None otherwise
        """
        if not self.settings.enabled or not self._last_screenshot:
            return None
            
        try:
            # Use targeted element detection
            element = await self.omniparser.find_element(
                screenshot_base64=self._last_screenshot,
                element_type=element_type,
                description_keywords=description_keywords,
                confidence_threshold=confidence_threshold
            )
            
            if element:
                logger.info(f"Found element with OmniParser: {element['type']} - {element['description']}")
                # Convert to DOM element
                return self._convert_to_dom_element(element, dom_state)
                
        except Exception as e:
            logger.error(f"Error finding specific element with OmniParser: {str(e)}")
            
        return None
    
    def _convert_to_dom_element(self, omni_element: Dict[str, Any], dom_state: DOMState) -> DOMElementNode:
        """Convert an OmniParser element to a DOM element."""
        bbox = omni_element.get("bbox", [0, 0, 0, 0])
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1
        
        # Create coordinate sets
        coordinates = CoordinateSet(
            top_left=Coordinates(x=x1, y=y1),
            top_right=Coordinates(x=x2, y=y1),
            bottom_left=Coordinates(x=x1, y=y2),
            bottom_right=Coordinates(x=x2, y=y2),
            center=Coordinates(x=x1 + width // 2, y=y1 + height // 2),
            width=width,
            height=height
        )
        
        # Create new element
        element = DOMElementNode(
            tag_name="div",
            xpath=f"//div[@data-omniparser-id='{omni_element.get('id')}']",
            attributes={
                "data-omniparser-id": omni_element.get("id", ""),
                "data-omniparser-type": omni_element.get("type", "unknown"),
                "data-omniparser-confidence": str(omni_element.get("confidence", 0.0)),
                "data-omniparser-detected": "true"
            },
            children=[],
            is_visible=True,
            is_interactive=True,
            is_top_element=True,
            is_in_viewport=True,
            highlight_index=len(dom_state.selector_map) + 1 if dom_state.selector_map else 1,
            shadow_root=False,
            parent=None,
            page_coordinates=coordinates,
            viewport_coordinates=coordinates  # Use same coordinates for viewport
        )
        
        # Add description as text node if available
        if description := omni_element.get("description"):
            text_node = DOMTextNode(
                text=description,
                is_visible=True,
                parent=element
            )
            element.children.append(text_node)
            
        return element
    
    async def _enhance_dom_state(self, dom_state: DOMState, screenshot_b64: str) -> DOMState:
        """Enhance DOM state with OmniParser results based on settings."""
        if self.settings.prefer_over_dom:
            # Try to get complete OmniParser state
            omni_state = self.omniparser.create_dom_state(screenshot_b64)
            if omni_state and omni_state.element_tree and len(omni_state.selector_map or {}) > 0:
                logger.info("Using OmniParser results instead of DOM-based extraction")
                return omni_state
        
        if self.settings.merge_with_dom:
            # Get OmniParser elements and merge
            omni_elements = await self.omniparser.detect_interactive_elements(screenshot_b64)
            if omni_elements:
                logger.info(f"Merging {len(omni_elements)} OmniParser elements with DOM results")
                return self._merge_with_dom(dom_state, omni_elements)
        
        return dom_state

    def _merge_with_dom(self, dom_state: DOMState, omni_elements: list) -> DOMState:
        """
        Merge OmniParser detected elements with DOM elements.
        
        Args:
            dom_state: Current DOM state
            omni_elements: List of elements detected by OmniParser
            
        Returns:
            Enhanced DOM state with merged elements
        """
        # Create a deep copy to avoid modifying the original
        new_dom = deepcopy(dom_state)
        
        # Function to check if a given OmniParser element overlaps with any DOM element
        def element_overlaps_with_dom(omni_element: Dict[str, Any], dom_element: Union[DOMElementNode, DOMBaseNode]) -> bool:
            if not dom_element:
                return False
                
            # Only proceed if we have a DOMElementNode
            if not isinstance(dom_element, DOMElementNode):
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
        def check_element_tree(element: Union[DOMElementNode, DOMBaseNode], overlapped_elements: Set[int]) -> None:
            if not element:
                return
                
            # Only proceed if we have a DOMElementNode
            if not isinstance(element, DOMElementNode):
                return
            
            for omni_element in omni_elements:
                if element_overlaps_with_dom(omni_element, element):
                    # Add OmniParser data to the element
                    if not hasattr(element, 'attributes') or element.attributes is None:
                        element.attributes = {}
                    element.attributes["data-omniparser-detected"] = "true"
                    element.attributes["data-omniparser-type"] = omni_element.get("element_type", "unknown")
                    element.attributes["data-omniparser-confidence"] = str(omni_element.get("confidence", 0.0))
                    
                    # Add text as a child text node if OmniParser found text
                    if omni_element.get("text"):
                        text_node = DOMTextNode(
                            text=omni_element.get("text"),
                            is_visible=True,
                            parent=element
                        )
                        element.children.append(text_node)
                    
                    overlapped_elements.add(id(omni_element))  # Use id() since dicts aren't hashable
        
            # Recursively check children
            if hasattr(element, 'children') and element.children:
                for child in element.children:
                    check_element_tree(child, overlapped_elements)
        
        # Track which OmniParser elements overlap with DOM elements
        overlapped_elements: Set[int] = set()
        
        # Start the recursive check
        if new_dom.element_tree:
            check_element_tree(new_dom.element_tree, overlapped_elements)
        
        # Add any non-overlapping OmniParser elements as new DOM elements
        for i, omni_element in enumerate(omni_elements):
            if id(omni_element) in overlapped_elements:
                continue
                
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
            
            # Add text as a child text node if present
            if omni_element.get("text"):
                text_node = DOMTextNode(
                    text=omni_element.get("text"),
                    is_visible=True,
                    parent=new_element
                )
                new_element.children.append(text_node)
            
            # Add to tree (as a child of body if no existing tree)
            if not new_dom.element_tree:
                # Create minimal tree
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
            
            # Update selector map with the element node (not just xpath)
            if new_dom.selector_map is None:
                new_dom.selector_map = {}
            if new_element.highlight_index is not None:
                new_dom.selector_map[new_element.highlight_index] = new_element
        
        return new_dom
