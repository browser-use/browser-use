import pytest
from browser_use.controller.views import NoParamsAction, SearchGoogleAction, SwitchTabAction, ClickElementAction
from pydantic import ValidationError
def test_no_params_action_ignores_input():
    """Test that NoParamsAction discards all provided input and results in an empty model."""
    # Provide arbitrary extra data
    instance = NoParamsAction(foo='bar', random_key=123, another={'subkey': 'value'})
    # Assert that the model is empty after validation, regardless of what was passed in
    assert instance.dict() == {}
    
def test_search_google_action_ignores_extra_keys():
    """Test that the SearchGoogleAction model ignores extra keys and only retains defined fields."""
    instance = SearchGoogleAction(query="python", extra_field=42)
    # Only the defined 'query' field should be kept.
    assert instance.dict() == {"query": "python"}
def test_switch_tab_action_invalid_page_id():
    """Test that providing a non-integer page_id in SwitchTabAction raises a ValidationError."""
    with pytest.raises(ValidationError):
        SwitchTabAction(page_id="not_an_int")
def test_click_element_action_defaults():
    """Test that ClickElementAction defaults are correctly set when optional fields are not provided."""
    instance = ClickElementAction(index=1)
    # Assert default values: xpath should be None and right_click should be False
    assert instance.dict() == {"index": 1, "xpath": None, "right_click": False}