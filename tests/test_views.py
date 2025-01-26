import pytest

from browser_use.browser.views import BrowserStateHistory, TabInfo
from unittest.mock import Mock

class TestBrowserStateHistory:
    """Tests for the BrowserStateHistory class"""

    def test_browser_state_history_to_dict(self):
        """
        Test that the to_dict method of BrowserStateHistory correctly converts the object to a dictionary.
        This test covers the scenario where we have a mix of tabs and interacted elements, including None values.
        """
        # Mock DOMHistoryElement
        mock_dom_element = Mock()
        mock_dom_element.to_dict.return_value = {"tag_name": "div", "attributes": {"id": "test"}}

        # Create mock data
        tabs = [
            TabInfo(page_id=1, url="https://example.com", title="Example"),
            TabInfo(page_id=2, url="https://test.com", title="Test")
        ]

        interacted_elements = [
            mock_dom_element,
            None,
            mock_dom_element
        ]

        # Create BrowserStateHistory instance
        browser_state_history = BrowserStateHistory(
            url="https://example.com",
            title="Example Page",
            tabs=tabs,
            interacted_element=interacted_elements,
            screenshot="base64_encoded_screenshot"
        )

        # Call to_dict method
        result = browser_state_history.to_dict()

        # Assert the structure and content of the resulting dictionary
        assert isinstance(result, dict)
        assert result["url"] == "https://example.com"
        assert result["title"] == "Example Page"
        assert len(result["tabs"]) == 2
        assert result["tabs"][0]["page_id"] == 1
        assert result["tabs"][1]["url"] == "https://test.com"
        assert len(result["interacted_element"]) == 3
        assert result["interacted_element"][0] == {"tag_name": "div", "attributes": {"id": "test"}}
        assert result["interacted_element"][1] is None
        assert result["interacted_element"][2] == {"tag_name": "div", "attributes": {"id": "test"}}
        assert result["screenshot"] == "base64_encoded_screenshot"