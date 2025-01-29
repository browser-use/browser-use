import pytest

from browser_use.dom.history_tree_processor.view import DOMHistoryElement

class TestDOMHistoryElement:
    def test_dom_history_element_to_dict(self):
        """
        Test that the to_dict() method of DOMHistoryElement correctly converts the object to a dictionary.
        This test covers the scenario where all fields are populated, including optional fields.
        """
        # Create a DOMHistoryElement instance with all fields populated
        dom_element = DOMHistoryElement(
            tag_name="div",
            xpath="/html/body/div[1]",
            highlight_index=1,
            entire_parent_branch_path=["html", "body", "div"],
            attributes={"class": "container", "id": "main"},
            shadow_root=True
        )

        # Call the to_dict() method
        result = dom_element.to_dict()

        # Assert that the result is a dictionary
        assert isinstance(result, dict)

        # Assert that all fields are present in the dictionary
        assert result["tag_name"] == "div"
        assert result["xpath"] == "/html/body/div[1]"
        assert result["highlight_index"] == 1
        assert result["entire_parent_branch_path"] == ["html", "body", "div"]
        assert result["attributes"] == {"class": "container", "id": "main"}
        assert result["shadow_root"] is True

        # Assert that the dictionary has all expected keys
        expected_keys = {"tag_name", "xpath", "highlight_index", "entire_parent_branch_path", "attributes", "shadow_root"}
        assert set(result.keys()) == expected_keys