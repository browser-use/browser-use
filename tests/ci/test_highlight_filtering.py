
import logging
import sys
from unittest.mock import MagicMock
from browser_use.browser.python_highlights import process_element_highlight
from browser_use.dom.views import EnhancedDOMTreeNode, DOMRect

# Configure logging to stdout
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

def test_highlight_filtering_logic_new_threshold():
    draw = MagicMock()
    font = MagicMock()
    draw.textbbox.return_value = (0, 0, 50, 20)
    
    element = MagicMock(spec=EnhancedDOMTreeNode)
    element.tag_name = "input"
    element.backend_node_id = 123
    element.attributes = {}
    # 14 chars < 50
    element.get_meaningful_text_for_llm.return_value = "Campbell River"
    element.absolute_position = DOMRect(x=10, y=10, width=100, height=20)
    
    import browser_use.browser.python_highlights as ph
    
    # Case 1: filter_highlight_ids=True (Default)
    # Expection: ID SHOULD be drawn now because 14 < 50
    print("\n--- Testing Case 1: Text length 14, Filter=True ---")
    process_element_highlight(
        element_id=1,
        element=element,
        draw=draw,
        device_pixel_ratio=1.0,
        font=font,
        filter_highlight_ids=True,
        image_size=(1000, 1000)
    )
    
    calls_with_id = [call for call in draw.text.mock_calls if "123" in str(call)]
    assert len(calls_with_id) > 0, "Should draw ID for 'Campbell River' (14 chars) because < 50"
    
    draw.reset_mock()
    
    # Case 2: Very long text > 50
    element.get_meaningful_text_for_llm.return_value = "A" * 55
    print("\n--- Testing Case 2: Text length 55, Filter=True ---")
    process_element_highlight(
        element_id=1,
        element=element,
        draw=draw,
        device_pixel_ratio=1.0,
        font=font,
        filter_highlight_ids=True,
        image_size=(1000, 1000)
    )
    
    calls_with_id = [call for call in draw.text.mock_calls if "123" in str(call)]
    assert len(calls_with_id) == 0, "Should NOT draw ID for 55 chars (> 50)"

