"""
Tests for the hybrid extractor.
"""

import base64
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from browser_use.dom.views import DOMElementNode, DOMState
from browser_use.dom.history_tree_processor.view import CoordinateSet, Coordinates, ViewportInfo
from browser_use.omniparser.hybrid_extractor import HybridExtractor
from browser_use.omniparser.views import OmniParserSettings


class TestHybridExtractor(unittest.TestCase):
    """Tests for the HybridExtractor class."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock the DOM service
        self.dom_service = MagicMock()
        self.dom_service.page = MagicMock()
        
        # Create sample DOM state for testing
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
        
        # Mock DOM service get_clickable_elements method
        self.dom_service.get_clickable_elements = AsyncMock(return_value=self.sample_dom_state)
        
        # Sample screenshot
        self.sample_screenshot = b"test_screenshot_data"
        self.dom_service.page.screenshot = AsyncMock(return_value=self.sample_screenshot)
        
        # Sample OmniParser results
        self.sample_omni_elements = [
            {
                "x": 150,
                "y": 150,
                "width": 100,
                "height": 30,
                "element_type": "button",
                "text": "Click Me",
                "confidence": 0.95
            },
            {
                "x": 300,
                "y": 300,
                "width": 150,
                "height": 40,
                "element_type": "checkbox",
                "text": "I am not a robot",
                "confidence": 0.89
            }
        ]
    
    @patch("browser_use.omniparser.service.OmniParserService")
    @patch("browser_use.omniparser.captcha.CaptchaDetector")
    async def test_get_elements_dom_only(self, mock_captcha_detector, mock_omniparser_service):
        """Test getting elements with DOM-only mode."""
        # Create settings with OmniParser disabled
        settings = OmniParserSettings(enabled=False)
        
        # Create the hybrid extractor
        extractor = HybridExtractor(self.dom_service, settings)
        
        # Get elements
        result = await extractor.get_elements()
        
        # Verify that only DOM extraction was used
        self.dom_service.get_clickable_elements.assert_called_once()
        self.assertEqual(result, self.sample_dom_state)
        
        # Verify OmniParser was not used
        mock_omniparser_service.return_value.detect_interactive_elements.assert_not_called()
    
    @patch("browser_use.omniparser.service.OmniParserService")
    @patch("browser_use.omniparser.captcha.CaptchaDetector")
    async def test_get_elements_with_omniparser_prefer(self, mock_captcha_detector, mock_omniparser_service):
        """Test getting elements with OmniParser preferred over DOM."""
        # Create settings with OmniParser enabled and preferred
        settings = OmniParserSettings(enabled=True, prefer_over_dom=True)
        
        # Create the hybrid extractor
        extractor = HybridExtractor(self.dom_service, settings)
        
        # Mock OmniParser service
        omniparser_mock = mock_omniparser_service.return_value
        omniparser_mock.create_dom_state_from_screenshot = AsyncMock(return_value=self.sample_dom_state)
        
        # Get elements
        result = await extractor.get_elements()
        
        # Verify that both extraction methods were used
        self.dom_service.get_clickable_elements.assert_called_once()
        omniparser_mock.create_dom_state_from_screenshot.assert_called_once()
        
        # Verify OmniParser result was used
        self.assertEqual(result, self.sample_dom_state)
    
    @patch("browser_use.omniparser.service.OmniParserService")
    @patch("browser_use.omniparser.captcha.CaptchaDetector")
    async def test_get_elements_with_captcha_detection(self, mock_captcha_detector, mock_omniparser_service):
        """Test getting elements with CAPTCHA detection enabled."""
        # Create settings with CAPTCHA detection enabled
        settings = OmniParserSettings(enabled=True, captcha_detection=True)
        
        # Create the hybrid extractor
        extractor = HybridExtractor(self.dom_service, settings)
        
        # Mock CAPTCHA detector
        captcha_detector_mock = mock_captcha_detector.return_value
        captcha_detector_mock.detect_captchas = AsyncMock(return_value=self.sample_omni_elements)
        captcha_detector_mock.enhance_dom_with_captchas = MagicMock(return_value=self.sample_dom_state)
        
        # Get elements
        result = await extractor.get_elements()
        
        # Verify that CAPTCHA detection was used
        captcha_detector_mock.detect_captchas.assert_called_once()
        captcha_detector_mock.enhance_dom_with_captchas.assert_called_once()
        
        # Verify the enhanced DOM was returned
        self.assertEqual(result, self.sample_dom_state)
    
    @patch("browser_use.omniparser.service.OmniParserService")
    @patch("browser_use.omniparser.captcha.CaptchaDetector")
    async def test_get_elements_with_merge(self, mock_captcha_detector, mock_omniparser_service):
        """Test getting elements with merging enabled."""
        # Create settings with merging enabled
        settings = OmniParserSettings(enabled=True, merge_with_dom=True)
        
        # Create the hybrid extractor
        extractor = HybridExtractor(self.dom_service, settings)
        
        # Mock OmniParser service
        omniparser_mock = mock_omniparser_service.return_value
        omniparser_mock.detect_interactive_elements = AsyncMock(return_value=self.sample_omni_elements)
        
        # Create a spy for _merge_with_dom
        original_merge = extractor._merge_with_dom
        merge_spy = MagicMock(side_effect=original_merge)
        extractor._merge_with_dom = merge_spy
        
        # Get elements
        result = await extractor.get_elements()
        
        # Verify that merging was used
        omniparser_mock.detect_interactive_elements.assert_called_once()
        merge_spy.assert_called_once()
        
        # The result should be the merged result
        self.assertEqual(merge_spy.return_value, result)


if __name__ == "__main__":
    unittest.main()
