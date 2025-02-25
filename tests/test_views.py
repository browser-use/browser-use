import pytest
from browser_use.controller.views import (
    ClickElementAction,
    InputTextAction,
    NoParamsAction,
    ScrollAction,
)


def test_no_params_action_discards_input():
    """
    Test that the NoParamsAction model ignores all provided input and results in an empty model.
    """
    test_input = {"unexpected": "value", "foo": 123, "bar": [1, 2, 3]}
    model = NoParamsAction(**test_input)
    assert model.dict() == {}


def test_click_element_action_defaults():
    """
    Test that ClickElementAction correctly assigns default values for optional parameters
    when only the required field is provided.
    """
    input_data = {"index": 2}
    action = ClickElementAction(**input_data)
    assert action.index == 2
    assert action.xpath is None
    assert action.right_click is False


def test_input_text_action_optional_xpath():
    """
    Test that InputTextAction correctly assigns the required 'index' and 'text' fields
    and that the optional 'xpath' field is set when provided and defaults to None when omitted.
    """
    input_data_with_xpath = {
        "index": 0,
        "text": "Hello, World!",
        "xpath": "//button[@id='submit']",
    }
    action_with_xpath = InputTextAction(**input_data_with_xpath)
    assert action_with_xpath.index == 0
    assert action_with_xpath.text == "Hello, World!"
    assert action_with_xpath.xpath == "//button[@id='submit']"
    input_data_without_xpath = {"index": 1, "text": "No XPath provided"}
    action_without_xpath = InputTextAction(**input_data_without_xpath)
    assert action_without_xpath.index == 1
    assert action_without_xpath.text == "No XPath provided"
    assert action_without_xpath.xpath is None


def test_scroll_action_optional_amount():
    """
    Test that ScrollAction defaults 'amount' to None when not provided,
    and correctly assigns the provided integer value.
    """
    scroll_default = ScrollAction()
    assert scroll_default.amount is None
    scroll_with_amount = ScrollAction(amount=120)
    assert scroll_with_amount.amount == 120
