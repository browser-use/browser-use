import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from browser_use.dom.views import DOMState, DOMElementNode
from browser_use.omniparser.hybrid_extractor import HybridExtractor
from browser_use.omniparser.views import OmniParserSettings
from browser_use.dom.service import DomService
from browser_use.dom.history_tree_processor.view import CoordinateSet, Coordinates


class TestOmniParserFallback(unittest.TestCase):
    """Tests for OmniParser fallback behavior in HybridExtractor."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock the DOM service
        self.dom_service = MagicMock(spec=DomService)
        self.dom_service.page = MagicMock()
        self.dom_service.page.screenshot = AsyncMock(return_value=b"fake_screenshot")

        # Create root element (body)
        self.root = DOMElementNode(
            tag_name="body",
            xpath="/html/body",
            attributes={},
            children=[],
            is_visible=True,
            is_interactive=False,
            is_top_element=True,
            is_in_viewport=True,
            highlight_index=0,
            shadow_root=False,
            parent=None,
            page_coordinates=CoordinateSet(
                top_left=Coordinates(x=0, y=0),
                top_right=Coordinates(x=1280, y=0),
                bottom_left=Coordinates(x=0, y=1024),
                bottom_right=Coordinates(x=1280, y=1024),
                center=Coordinates(x=640, y=512),
                width=1280,
                height=1024
            ),
            viewport_coordinates=None
        )
        
        # Create button element
        self.button = DOMElementNode(
            tag_name="button",
            xpath="//button",
            attributes={},
            children=[],
            is_visible=True,
            is_interactive=True,
            is_top_element=True,
            is_in_viewport=True,
            highlight_index=1,
            shadow_root=False,
            parent=self.root,
            page_coordinates=None,
            viewport_coordinates=None
        )
        
        # Create input field element
        self.input_field = DOMElementNode(
            tag_name="input",
            xpath="//input",
            attributes={"type": "text"},
            children=[],
            is_visible=True,
            is_interactive=True,
            is_top_element=True,
            is_in_viewport=True,
            highlight_index=2,
            shadow_root=False,
            parent=self.root,
            page_coordinates=None,
            viewport_coordinates=None
        )
        
        # Add children to root
        self.root.children = [self.button, self.input_field]
        
        # Create base DOM state
        self.base_dom_state = DOMState(
            element_tree=self.root,
            selector_map={
                1: self.button,
                2: self.input_field
            }
        )
        
        # Mock DOM service get_clickable_elements method
        self.dom_service.get_clickable_elements = AsyncMock(return_value=self.base_dom_state)

    @patch("browser_use.omniparser.service.OmniParserService")
    @patch("browser_use.omniparser.captcha.CaptchaDetector")
    async def test_fallback_with_required_elements(self, mock_captcha_detector, mock_omniparser_service):
        """Test that OmniParser fallback is triggered when required elements are missing"""
        # Setup
        settings = OmniParserSettings(
            enabled=True,
            use_as_fallback=True,
            min_expected_elements=1,
            required_elements=["submit", "text"]
        )
        
        extractor = HybridExtractor(self.dom_service, settings)
        
        # Create a mock OmniParser element
        submit_button = {
            "type": "submit",
            "description": "Submit Form",
            "bbox": [10, 10, 100, 40],
            "confidence": 0.9,
            "id": "submit-1"
        }
        
        # Mock OmniParser service
        omniparser_mock = mock_omniparser_service.return_value
        omniparser_mock.detect_interactive_elements = AsyncMock(return_value=[submit_button])
        
        # Get elements
        result = await extractor.get_elements(required_elements=["submit", "text"])
        
        # Verify that OmniParser detection was called exactly once
        omniparser_mock.detect_interactive_elements.assert_called_once()
        
        # Verify that the result includes both DOM elements and OmniParser detected elements
        self.assertIsNotNone(result, "Result should not be None")
        self.assertGreaterEqual(len(result.selector_map), 3, "Result should include original elements plus new ones")

    @patch("browser_use.omniparser.service.OmniParserService")
    @patch("browser_use.omniparser.captcha.CaptchaDetector")
    async def test_no_fallback_when_required_elements_present(self, mock_captcha_detector, mock_omniparser_service):
        """Test that OmniParser fallback is not triggered when all required elements are present"""
        # Add a submit button to the mock DOM state
        submit_button = DOMElementNode(
            tag_name="button",
            xpath="//button[2]",
            attributes={"type": "submit"},
            children=[],
            is_visible=True,
            is_interactive=True,
            is_top_element=True,
            is_in_viewport=True,
            highlight_index=3,
            shadow_root=False,
            parent=self.root,
            page_coordinates=None,
            viewport_coordinates=None
        )
        
        self.root.children.append(submit_button)
        self.base_dom_state.selector_map[3] = submit_button
        
        # Setup
        settings = OmniParserSettings(
            enabled=True,
            use_as_fallback=True,
            min_expected_elements=1,
            required_elements=["submit", "text"]
        )
        
        extractor = HybridExtractor(self.dom_service, settings)
        
        # Get elements
        result = await extractor.get_elements(required_elements=["submit", "text"])
        
        # Verify that the result is the same as the input DOM state (no OmniParser fallback)
        self.assertEqual(result, self.base_dom_state)
        
        # Verify that OmniParser was not called
        mock_omniparser_service.return_value.detect_interactive_elements.assert_not_called()

    @patch("browser_use.omniparser.service.OmniParserService")
    @patch("browser_use.omniparser.captcha.CaptchaDetector")
    async def test_llm_prediction_failure_recovery(self, mock_captcha_detector, mock_omniparser_service):
        """Test recovery from LLM prediction failure by falling back to OmniParser"""
        # Create empty DOM state
        empty_dom_state = DOMState(
            element_tree=DOMElementNode(
                tag_name="body",
                xpath="/html/body",
                attributes={},
                children=[],
                is_visible=True,
                is_interactive=False,
                is_top_element=True,
                is_in_viewport=True,
                highlight_index=0,
                shadow_root=False,
                parent=None,
                page_coordinates=self.root.page_coordinates,
                viewport_coordinates=None
            ),
            selector_map={}
        )
        
        self.dom_service.get_clickable_elements.return_value = empty_dom_state
        
        # Setup
        settings = OmniParserSettings(
            enabled=True,
            use_as_fallback=True,
            min_expected_elements=1,
            required_elements=["submit"]
        )
        
        extractor = HybridExtractor(self.dom_service, settings)
        
        # Create mock OmniParser elements
        submit_button = {
            "type": "submit",
            "description": "Submit Form",
            "bbox": [10, 10, 100, 40],
            "confidence": 0.9,
            "id": "submit-1"
        }
        
        # Mock OmniParser service
        omniparser_mock = mock_omniparser_service.return_value
        omniparser_mock.detect_interactive_elements = AsyncMock(return_value=[submit_button])
        
        # Get elements
        result = await extractor.get_elements(required_elements=["submit"])
        
        # Verify that OmniParser detection was called exactly once
        omniparser_mock.detect_interactive_elements.assert_called_once()
        
        # Verify that the result includes the required submit button
        self.assertIsNotNone(result, "Result should not be None")
        self.assertGreater(len(result.selector_map), 0, "Result should contain elements")
        
        # Verify that at least one element is a submit button
        found_submit = False
        for element in result.selector_map.values():
            if ((element.tag_name == "button" and element.attributes.get("type") == "submit") or
                element.attributes.get("data-omniparser-type") == "submit"):
                found_submit = True
                break
        
        self.assertTrue(found_submit, "Submit button not found in result")

    @patch("browser_use.omniparser.service.OmniParserService")
    @patch("browser_use.omniparser.captcha.CaptchaDetector")
    async def test_hybrid_extraction_with_captcha(self, mock_captcha_detector, mock_omniparser_service):
        """Test that hybrid extraction properly handles CAPTCHA detection"""
        # Setup
        settings = OmniParserSettings(
            enabled=True,
            use_as_fallback=False,  # Always use OmniParser
            captcha_detection=True,
            min_expected_elements=100  # Set high to force fallback
        )
        
        extractor = HybridExtractor(self.dom_service, settings)
        
        # Create a mock CAPTCHA element
        captcha_element = {
            "type": "captcha",
            "description": "CAPTCHA Challenge",
            "bbox": [10, 10, 200, 100],
            "confidence": 0.95,
            "id": "captcha-1"
        }
        
        # Create a mock DOM state for CAPTCHA
        captcha_dom_element = DOMElementNode(
            tag_name="div",
            xpath="/html/body/div[@id='captcha-0']",
            attributes={"data-captcha": "true", "data-captcha-confidence": "0.95"},
            children=[],
            is_visible=True,
            is_interactive=True,
            is_top_element=True,
            is_in_viewport=True,
            highlight_index=3,
            shadow_root=False,
            parent=self.root,
            page_coordinates=None,
            viewport_coordinates=None
        )
        
        # Add CAPTCHA element to base DOM state
        self.root.children.append(captcha_dom_element)
        self.base_dom_state.selector_map[3] = captcha_dom_element
        
        # Mock CAPTCHA detector
        captcha_detector_mock = mock_captcha_detector.return_value
        captcha_detector_mock.detect_captchas = AsyncMock(return_value=[captcha_element])
        
        # Get elements
        result = await extractor.get_elements()
        
        # Verify CAPTCHA detection was called
        captcha_detector_mock.detect_captchas.assert_called_once()
        
        # Verify that the result includes the CAPTCHA element
        self.assertIsNotNone(result, "Result should not be None")
        
        # The result should have the original elements plus the CAPTCHA element
        original_count = len(self.base_dom_state.selector_map)
        result_count = len(result.selector_map)
        self.assertGreater(result_count, original_count, 
                          f"Expected more than {original_count} elements, got {result_count}")
        
        # Verify that the CAPTCHA element was added with proper attributes
        found_captcha = False
        for element in result.selector_map.values():
            if (element.attributes.get("data-omniparser-type") == "captcha" or
                element.attributes.get("data-captcha") == "true"):
                found_captcha = True
                break
        
        self.assertTrue(found_captcha, "CAPTCHA element not found in result")


if __name__ == "__main__":
    unittest.main() 