import pytest
from browser_use.controller.views import (
    ClickElementAction,
    DoneAction,
    NoParamsAction,
    ScrollAction,
)


def test_no_params_action_ignores_all_inputs():
    """
    Test that NoParamsAction ignores any input provided, resulting in an empty model.
    """
    input_data = {
        "unexpected_field": "value",
        "another_field": 123,
        "more": {"nested": "data"},
    }
    model_instance = NoParamsAction.parse_obj(input_data)
    assert model_instance.dict() == {}


def test_click_element_action_defaults():
    """
    Test that ClickElementAction assigns default values for optional fields when they are omitted.
    """
    input_data = {"index": 5}
    model_instance = ClickElementAction.parse_obj(input_data)
    assert model_instance.index == 5, "Expected index to be 5"
    assert model_instance.xpath is None, "Expected xpath to be None by default"
    assert (
        model_instance.right_click is False
    ), "Expected right_click to default to False"


def test_done_action_parses_correctly():
    """
    Test that DoneAction correctly parses input data and returns a dict with the expected fields.
    """
    input_data = {"text": "Operation completed", "success": True}
    model_instance = DoneAction.parse_obj(input_data)
    expected_dict = {"text": "Operation completed", "success": True}
    assert (
        model_instance.dict() == expected_dict
    ), "DoneAction did not output the expected dictionary"


def test_scroll_action_defaults_and_custom():
    """
    Test that ScrollAction correctly defaults the 'amount' field to None when omitted,
    and sets it to a provided integer value when present.
    """
    instance_default = ScrollAction.parse_obj({})
    assert instance_default.amount is None, "Expected default 'amount' to be None"
    test_value = 250
    instance_custom = ScrollAction.parse_obj({"amount": test_value})
    assert (
        instance_custom.amount == test_value
    ), f"Expected 'amount' to equal {test_value}"
