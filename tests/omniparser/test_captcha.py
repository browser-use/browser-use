"""
Tests for the CAPTCHA detector.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from browser_use.dom.views import DOMElementNode, DOMState
from browser_use.dom.history_tree_processor.view import CoordinateSet, Coordinates, ViewportInfo
from browser_use.omniparser.captcha import CaptchaDetector
from browser_use.omniparser.service import OmniParserService
from browser_use.omniparser.views import OmniParserSettings


class TestCaptchaDetector(unittest.TestCase):
    """Tests for the CaptchaDetector class."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock the OmniParser service
        self.omniparser_service = MagicMock(spec=OmniParserService)
        
        # Sample DOM state
        self.sample_dom_state = DOMState(
            element_tree=DOMElementNode(
                tag_name="body",
                xpath="/body",
                attributes={},
                children=[
                    DOMElementNode(
                        tag_name="div",
                        xpath="/body/div",
                        attributes={"id": "test-div"},
                        children=[],
                        is_visible=True,
                        is_interactive=True,
                        is_top_element=True,
                        is_in_viewport=True,
                        highlight_index=1,
                        shadow_root=False,
                        parent=None,
                        page_coordinates=CoordinateSet(
                            top_left=Coordinates(x=100, y=100),
                            top_right=Coordinates(x=300, y=100),
                            bottom_left=Coordinates(x=100, y=150),
                            bottom_right=Coordinates(x=300, y=150),
                            center=Coordinates(x=200, y=125),
                            width=200,
                            height=50
                        )
                    )
                ],
                is_visible=True,
                is_interactive=False,
                is_top_element=False,
                is_in_viewport=True,
                highlight_index=0,
                shadow_root=False,
                parent=None,
                page_coordinates=CoordinateSet(
                    top_left=Coordinates(x=0, y=0),
                    top_right=Coordinates(x=1280, y=0),
                    bottom_left=Coordinates(x=0, y=720),
                    bottom_right=Coordinates(x=1280, y=720),
                    center=Coordinates(x=640, y=360),
                    width=1280,
                    height=720
                )
            ),
            selector_map={
                0: "body",
                1: "#test-div"
            }
        )
        
        # Sample CAPTCHA elements
        self.sample_captcha_elements = [
            {
                "x": 150,
                "y": 150,
                "width": 100,
                "height": 30,
                "element_type": "checkbox",
                "text": "I am not a robot",
                "confidence": 0.95
            },
            {
                "x": 300,
                "y": 300,
                "width": 150,
                "height": 40,
                "element_type": "image",
                "text": "select all images with traffic lights",
                "confidence": 0.89
            }
        ]
        
        # Create the detector
        self.detector = CaptchaDetector(
            self.omniparser_service,
            OmniParserSettings(captcha_detection=True)
        )
    
    async def test_detect_captchas(self):
        """Test detecting CAPTCHA elements."""
        # Mock OmniParser service to return sample elements
        self.omniparser_service.detect_interactive_elements = AsyncMock(
            return_value=self.sample_captcha_elements
        )
        
        # Call the method
        result = await self.detector.detect_captchas("test_screenshot")
        
        # Verify the service was called
        self.omniparser_service.detect_interactive_elements.assert_called_once_with(
            "test_screenshot", 
            confidence_threshold=self.detector.settings.confidence_threshold
        )
        
        # Verify all CAPTCHA elements were detected (using our mock sample)
        self.assertEqual(len(result), 2)
    
    def test_is_likely_captcha(self):
        """Test CAPTCHA likelihood detection logic."""
        # Test cases with various element types and text content
        test_cases = [
            # Checkboxes are commonly used in reCAPTCHA
            ({"element_type": "checkbox"}, True),
            
            # Text matches for common CAPTCHA providers
            ({"element_type": "div", "text": "complete recaptcha verification"}, True),
            ({"element_type": "div", "text": "hcaptcha challenge"}, True),
            
            # Text matches for common CAPTCHA phrases
            ({"element_type": "div", "text": "verify you're human"}, True),
            ({"element_type": "div", "text": "i am not a robot"}, True),
            
            # Image challenges in CAPTCHAs
            ({"element_type": "image", "text": "select all traffic lights"}, True),
            
            # Non-CAPTCHA elements
            ({"element_type": "button", "text": "submit form"}, False),
            ({"element_type": "input", "text": "enter your name"}, False)
        ]
        
        # Test each case
        for element, expected in test_cases:
            with self.subTest(element=element):
                result = self.detector._is_likely_captcha(element)
                self.assertEqual(result, expected)
    
    def test_enhance_dom_with_captchas(self):
        """Test enhancing the DOM with CAPTCHA information."""
        # Call the method
        enhanced_dom = self.detector.enhance_dom_with_captchas(
            self.sample_dom_state,
            self.sample_captcha_elements
        )
        
        # Verify the DOM was modified (not the same object)
        self.assertIsNot(enhanced_dom, self.sample_dom_state)
        
        # Verify CAPTCHA information was added to the DOM
        # This is a complex check since we're modifying a tree structure
        # We'll just verify some key properties are present
        
        # Check if new CAPTCHA elements were added
        # The sample CAPTCHA doesn't overlap with the existing element
        # so we should have one new element in the selector map
        self.assertGreater(len(enhanced_dom.selector_map), len(self.sample_dom_state.selector_map))
        
        # Find elements with CAPTCHA markers
        captcha_elements = []
        
        def find_captcha_elements(element):
            if element is None:
                return
            
            if element.attributes and "data-captcha" in element.attributes:
                captcha_elements.append(element)
            
            if element.children:
                for child in element.children:
                    find_captcha_elements(child)
        
        find_captcha_elements(enhanced_dom.element_tree)
        
        # Verify we found at least one CAPTCHA element
        self.assertGreater(len(captcha_elements), 0)


if __name__ == "__main__":
    unittest.main()
