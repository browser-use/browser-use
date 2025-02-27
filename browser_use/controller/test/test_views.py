import pytest
from pydantic import ValidationError
from browser_use.controller.views import (
    SearchGoogleAction,
    GoToUrlAction,
    ClickElementAction,
    InputTextAction,
    DoneAction,
    SwitchTabAction,
    OpenTabAction,
    ScrollAction,
    SendKeysAction,
    ExtractPageContentAction,
    NoParamsAction
)

def test_search_google_valid():
    """Test SearchGoogleAction with valid input."""
    action = SearchGoogleAction(query="python")
    assert action.query == "python"

def test_search_google_invalid():
    """Test SearchGoogleAction raises error when required field is missing."""
    with pytest.raises(ValidationError):
        SearchGoogleAction()

def test_go_to_url_valid():
    """Test GoToUrlAction with valid input."""
    action = GoToUrlAction(url="https://www.example.com")
    assert action.url == "https://www.example.com"

def test_click_element_defaults():
    """Test ClickElementAction with default values for the optional fields."""
    action = ClickElementAction(index=2)
    assert action.index == 2
    assert action.xpath is None
    assert action.right_click is False

def test_click_element_all_fields():
    """Test ClickElementAction with all fields provided."""
    action = ClickElementAction(index=3, xpath="//div", right_click=True)
    assert action.index == 3
    assert action.xpath == "//div"
    assert action.right_click is True

def test_input_text_action():
    """Test InputTextAction with required and optional field."""
    action = InputTextAction(index=1, text="hello")
    assert action.index == 1
    assert action.text == "hello"
    assert action.xpath is None

def test_done_action():
    """Test DoneAction with a boolean flag."""
    action = DoneAction(text="Finished", success=True)
    assert action.text == "Finished"
    assert action.success is True

def test_switch_tab_action():
    """Test SwitchTabAction with page_id."""
    action = SwitchTabAction(page_id=2)
    assert action.page_id == 2

def test_open_tab_action():
    """Test OpenTabAction with valid url."""
    action = OpenTabAction(url="https://www.open.com")
    assert action.url == "https://www.open.com"

def test_scroll_action_default():
    """Test ScrollAction with no amount provided (should be None)."""
    action = ScrollAction()
    assert action.amount is None

def test_scroll_action_with_amount():
    """Test ScrollAction with a specified amount."""
    action = ScrollAction(amount=100)
    assert action.amount == 100

def test_send_keys_action():
    """Test SendKeysAction with provided keys."""
    action = SendKeysAction(keys="Enter")
    assert action.keys == "Enter"

def test_extract_page_content_action():
    """Test ExtractPageContentAction with given value."""
    action = ExtractPageContentAction(value="content")
    assert action.value == "content"

def test_no_params_action_ignores_input():
    """Test NoParamsAction to ensure it ignores all provided inputs."""
    # Provide extra fields that should be discarded by the model_validator
    action = NoParamsAction(foo="bar", baz=123)
    # The resulting model should have an empty dict of values.
    assert action.dict() == {}
def test_click_element_invalid_type():
    """Test ClickElementAction raises validation error when index is not an integer."""
    with pytest.raises(ValidationError):
        ClickElementAction(index="not_an_int")

def test_input_text_action_with_xpath():
    """Test InputTextAction properly accepts an xpath value along with required fields."""
    action = InputTextAction(index=5, text="test input", xpath="//input[@type='text']")
    assert action.index == 5
    assert action.text == "test input"
    assert action.xpath == "//input[@type='text']"

def test_extra_field_on_non_no_params_action():
    """Test that providing an extra field to a model that does not forbid extras ignores the extra field."""
    action = SearchGoogleAction(query="python", unexpected_field="unexpected")
    assert action.dict() == {"query": "python"}

def test_scroll_action_invalid_amount():
    """Test ScrollAction raises a validation error when amount cannot be converted to integer."""
    with pytest.raises(ValidationError):
        ScrollAction(amount="abc")

def test_done_action_invalid_flag():
    """Test that DoneAction converts a non-boolean value for success to a boolean."""
    action = DoneAction(text="Completed", success="yes")
    # Since "yes" is truthy, it is coerced to True by Pydantic
    assert action.success is True

def test_no_params_action_without_extra():
    """Test NoParamsAction returns an empty dict when no extra input is provided."""
    action = NoParamsAction()
    assert action.dict() == {}
def test_done_action_bool_coercion_zero():
    """Test DoneAction converts numeric 0 to boolean False."""
    action = DoneAction(text="Test with 0", success=0)
    assert action.success is False

def test_send_keys_int_cast_invalid():
    """Test SendKeysAction raises a ValidationError for non-string keys input."""
    with pytest.raises(ValidationError):
        SendKeysAction(keys=123)
def test_search_google_int_query_invalid():
    """Test SearchGoogleAction raises a ValidationError for non-string query input."""
    with pytest.raises(ValidationError):
        SearchGoogleAction(query=456)
def test_click_element_extra_field():
    """Test ClickElementAction ignores extra fields not defined in the schema."""
    action = ClickElementAction(index=5, extra="should be ignored")
    # The extra field 'extra' should not be included in the model's dict.
    assert action.dict() == {"index": 5, "xpath": None, "right_click": False}

def test_open_tab_action_extra_field():
    """Test OpenTabAction ignores any extra fields provided."""
    action = OpenTabAction(url="https://test.com", extra="ignored")
    assert action.dict() == {"url": "https://test.com"}

def test_scroll_action_negative_amount():
    """Test ScrollAction accepts negative values for the amount without error."""
    action = ScrollAction(amount=-50)
    assert action.amount == -50

def test_input_text_action_extra_field():
    """Test InputTextAction ignores extra fields beyond its defined schema."""
    action = InputTextAction(index=10, text="sample", extra_data="ignored")
    assert action.dict() == {"index": 10, "text": "sample", "xpath": None}