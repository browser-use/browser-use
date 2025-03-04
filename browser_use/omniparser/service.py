"""
OmniParser service implementation.

This service provides methods to use Microsoft's OmniParser 2.0 for processing
screenshots and detecting interactive UI elements, particularly those that are
challenging for traditional DOM-based extraction.
"""

import base64
import io
import logging
import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any

import requests
from PIL import Image

# Import when OmniParser is installed
try:
    from omniparser import OmniParser # type: ignore
    OMNIPARSER_AVAILABLE = True
except ImportError:
    OMNIPARSER_AVAILABLE = False

from browser_use.dom.views import DOMElementNode, DOMState, SelectorMap

logger = logging.getLogger(__name__)


@dataclass
class DetectedElement:
    """Representation of an element detected by OmniParser."""
    type: str  # Element type (button, checkbox, etc.)
    description: str  # Functional description
    x1: float  # Bounding box coordinates
    y1: float
    x2: float
    y2: float
    confidence: float  # Detection confidence score


class OmniParserService:
    """Service for integrating with Microsoft OmniParser."""

    def __init__(self, 
                 weights_dir: Optional[str] = None, 
                 api_key: Optional[str] = None,
                 use_api: bool = True):
        """Initialize the OmniParser service.
        
        Args:
            weights_dir: Directory containing the OmniParser model weights.
                         If None, will use the default location.
            api_key: API key for the hosted OmniParser service.
            use_api: Whether to use the hosted API when local installation is not available.
        """
        self.weights_dir = weights_dir
        self.api_key = api_key
        self.use_api = use_api
        self.api_endpoint = "https://api.screenparse.ai/v1/screen/parse"
        self._omniparser = None
        self._initialized = False
        self._last_processed_elements = []  # Cache last processed elements to avoid reprocessing

    def is_available(self) -> bool:
        """Check if OmniParser is available."""
        return OMNIPARSER_AVAILABLE or (self.use_api and self.api_endpoint is not None)

    def _ensure_initialized(self) -> bool:
        """Ensure OmniParser is initialized."""
        if OMNIPARSER_AVAILABLE:
            if not self._initialized:
                try:
                    # If weights_dir is None, OmniParser will use its default location
                    self._omniparser = OmniParser(model_dir=self.weights_dir)
                    self._initialized = True
                    logger.info("OmniParser initialized successfully (local)")
                except Exception as e:
                    logger.error(f"Failed to initialize local OmniParser: {str(e)}")
                    if not self.use_api:
                        return False
                    logger.info("Falling back to hosted OmniParser API")
            return True
        elif self.use_api:
            logger.info("Using hosted OmniParser API (local installation not available)")
            return True
        else:
            logger.warning("OmniParser is not available. Install it with 'pip install omniparser' or enable API usage")
            return False
    
    def process_screenshot(self, screenshot_base64: str) -> List[DetectedElement]:
        """Process a screenshot using OmniParser.
        
        Args:
            screenshot_base64: Base64-encoded screenshot image
            
        Returns:
            List of detected elements
        """
        if not self._ensure_initialized():
            logger.warning("OmniParser is not initialized, returning empty results")
            return []
        
        try:
            if OMNIPARSER_AVAILABLE and self._omniparser:
                # Use local OmniParser
                return self._process_local(screenshot_base64)
            elif self.use_api:
                # Use hosted API
                return self._process_api(screenshot_base64)
            else:
                return []
        except Exception as e:
            logger.error(f"Error processing screenshot with OmniParser: {str(e)}")
            return []
    
    def _process_local(self, screenshot_base64: str) -> List[DetectedElement]:
        """Process a screenshot using local OmniParser installation."""
        # Decode base64 image
        image_bytes = base64.b64decode(screenshot_base64)
        image = Image.open(io.BytesIO(image_bytes))
        
        # Process image with OmniParser
        raw_results = self._omniparser.parse_image(image)
        
        # Convert results to DetectedElement objects
        elements = []
        for raw_element in raw_results:
            element = DetectedElement(
                type=raw_element.get('element_type', 'unknown'),
                description=raw_element.get('text', ''),
                x1=raw_element.get('x', 0),
                y1=raw_element.get('y', 0),
                x2=raw_element.get('x', 0) + raw_element.get('width', 0),
                y2=raw_element.get('y', 0) + raw_element.get('height', 0),
                confidence=raw_element.get('confidence', 0.0)
            )
            elements.append(element)
        
        return elements
    
    def _process_api(self, screenshot_base64: str) -> List[DetectedElement]:
        """Process a screenshot using the hosted OmniParser API."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        # Prepare image URL (data URL in this case)
        image_url = f"data:image/png;base64,{screenshot_base64}"
        
        # Make API request
        try:
            response = requests.post(
                self.api_endpoint, 
                json={"image_url": image_url},
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            # Convert API response to DetectedElement objects
            elements = []
            for element in data.get("elements", []):
                bbox = element.get("bbox_px", [0, 0, 0, 0])
                elements.append(DetectedElement(
                    type=element.get("type", "unknown"),
                    description=element.get("content", ""),
                    x1=bbox[0],
                    y1=bbox[1],
                    x2=bbox[2],
                    y2=bbox[3],
                    # Set confidence to 0.9 for interactive elements, 0.7 for non-interactive
                    confidence=0.9 if element.get("is_interactive", False) else 0.7
                ))
            
            return elements
        except Exception as e:
            logger.error(f"Error calling OmniParser API: {str(e)}")
            return []

    async def detect_interactive_elements(
        self, 
        screenshot_base64: str, 
        confidence_threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Detect interactive elements in a screenshot.
        
        This method wraps process_screenshot and applies additional filtering
        based on confidence threshold.
        
        Args:
            screenshot_base64: Base64-encoded screenshot image
            confidence_threshold: Minimum confidence score for detection (0.0 to 1.0)
            
        Returns:
            List of detected elements in a format compatible with the DOM merger
        """
        elements = self.process_screenshot(screenshot_base64)
        
        # Filter by confidence threshold
        filtered_elements = [
            element for element in elements
            if element.confidence >= confidence_threshold
        ]
        
        # Convert to dictionary format expected by consumers
        result = []
        for idx, element in enumerate(filtered_elements):
            result.append({
                "type": element.type,
                "description": element.description,
                "bbox": [element.x1, element.y1, element.x2, element.y2],
                "confidence": element.confidence,
                "id": f"omni-{idx}"  # Add unique ID for reference
            })
        
        return result

    def convert_to_dom_elements(self, 
                               detected_elements: List[DetectedElement],
                               image_width: int,
                               image_height: int) -> Tuple[DOMElementNode, SelectorMap]:
        """Convert OmniParser detected elements to BrowseUse DOM elements.
        
        Args:
            detected_elements: List of elements detected by OmniParser
            image_width: Width of the original image
            image_height: Height of the original image
            
        Returns:
            Tuple containing:
            - Root DOMElementNode containing the detected elements
            - SelectorMap mapping highlight indices to elements
        """
        # Create root element
        root = DOMElementNode(
            tag_name="body",
            xpath="/html/body",
            attributes={},
            children=[],
            is_visible=True,
            is_interactive=False,
            is_top_element=False,
            is_in_viewport=True,
            highlight_index=None,
            shadow_root=False,
            parent=None,
        )
        
        # Create selector map
        selector_map = {}
        
        # Process each detected element
        for i, element in enumerate(detected_elements):
            # Create a unique highlight index for this element
            highlight_index = i + 1
            
            # Generate an xpath that includes element description for better identification
            safe_description = element.description.replace('"', '').replace("'", "")
            element_xpath = f"//omniparser-element[@description='{safe_description}']"
            
            # Calculate viewport coordinates
            # (normalize to match DOMElementNode expected format)
            element_node = DOMElementNode(
                tag_name="omniparser-element",
                xpath=element_xpath,
                attributes={
                    "type": element.type,
                    "description": element.description,
                    "confidence": str(element.confidence),
                    "x1": str(element.x1),
                    "y1": str(element.y1),
                    "x2": str(element.x2),
                    "y2": str(element.y2),
                },
                children=[],
                is_visible=True,
                is_interactive=True,
                is_top_element=True,
                is_in_viewport=True,
                highlight_index=highlight_index,
                shadow_root=False,
                parent=root,
            )
            
            # Add to root's children
            root.children.append(element_node)
            
            # Add to selector map
            selector_map[highlight_index] = element_node
        
        return root, selector_map

    def create_dom_state(self,
                         screenshot_base64: str,
                         image_width: Optional[int] = None,
                         image_height: Optional[int] = None) -> Optional[DOMState]:
        """Process a screenshot and create a DOMState with detected elements.
        
        Args:
            screenshot_base64: Base64-encoded screenshot image
            image_width: Width of the image (if known)
            image_height: Height of the image (if known)
            
        Returns:
            DOMState containing the detected elements or None if processing failed
        """
        try:
            # If dimensions aren't provided, extract them from the image
            if image_width is None or image_height is None:
                image_data = base64.b64decode(screenshot_base64)
                image = Image.open(io.BytesIO(image_data))
                image_width, image_height = image.size
            
            # Process with OmniParser
            detected_elements = self.process_screenshot(screenshot_base64)
            
            if not detected_elements:
                logger.warning("No elements detected by OmniParser")
                return None
                
            # Convert to DOM elements
            element_tree, selector_map = self.convert_to_dom_elements(
                detected_elements, image_width, image_height
            )
            
            # Create and return DOM state
            return DOMState(element_tree=element_tree, selector_map=selector_map)
            
        except Exception as e:
            logger.error(f"Error creating DOM state with OmniParser: {str(e)}")
            return None

    async def find_element(self, 
                          screenshot_base64: str,
                          element_type: Optional[str] = None,
                          description_keywords: Optional[List[str]] = None,
                          confidence_threshold: float = 0.5) -> Optional[Dict[str, Any]]:
        """Find a specific element in the screenshot using OmniParser.
        
        This is a targeted approach that only processes the screenshot when needed,
        specifically looking for elements matching the given criteria.
        
        Args:
            screenshot_base64: Base64-encoded screenshot image
            element_type: Type of element to look for (e.g., "button", "input", etc.)
            description_keywords: List of keywords to match in element descriptions
            confidence_threshold: Minimum confidence score for detection
            
        Returns:
            Matching element details if found, None otherwise
        """
        # First check if we have cached results to avoid reprocessing
        if not self._last_processed_elements:
            elements = await self.detect_interactive_elements(
                screenshot_base64,
                confidence_threshold=confidence_threshold
            )
            self._last_processed_elements = elements
        else:
            elements = self._last_processed_elements

        # Filter elements based on criteria
        matching_elements = []
        for element in elements:
            matches = True
            
            if element_type and element["type"].lower() != element_type.lower():
                matches = False
                
            if description_keywords:
                desc = element["description"].lower()
                if not any(keyword.lower() in desc for keyword in description_keywords):
                    matches = False
                    
            if matches and element["confidence"] >= confidence_threshold:
                matching_elements.append(element)

        # Sort by confidence and return the best match
        if matching_elements:
            return sorted(matching_elements, key=lambda x: x["confidence"], reverse=True)[0]
            
        return None

    def clear_cache(self):
        """Clear the cached elements from the last processing."""
        self._last_processed_elements = []
