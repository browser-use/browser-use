import pytest
from browser_use.agent.prompts import (
    AgentMessagePrompt,
    PlannerPrompt,
    SystemPrompt,
)
from browser_use.agent.views import (
    ActionResult,
)
from datetime import (
    datetime,
)
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)
from typing import (
    List,
    Optional,
)


class DummyElementTree:

    def clickable_elements_to_string(self, include_attributes):
        return "<div>Test Interactive Element</div>"


class DummyStepInfo:

    def __init__(self, step_number, max_steps):
        self.step_number = step_number
        self.max_steps = max_steps


class DummyBrowserState:

    def __init__(self, url, tabs, element_tree, pixels_above, pixels_below, screenshot):
        self.url = url
        self.tabs = tabs
        self.element_tree = element_tree
        self.pixels_above = pixels_above
        self.pixels_below = pixels_below
        self.screenshot = screenshot


def test_agent_message_prompt_with_screenshot():
    """
    Test AgentMessagePrompt.get_user_message when a screenshot is provided.
    Verifies that the method returns a HumanMessage with a list containing
    both text and image payload (vision branch).
    """
    dummy_element_tree = DummyElementTree()
    dummy_step_info = DummyStepInfo(step_number=0, max_steps=3)
    dummy_state = DummyBrowserState(
        url="http://test.com",
        tabs="Tab1, Tab2",
        element_tree=dummy_element_tree,
        pixels_above=15,
        pixels_below=25,
        screenshot="fake_base64encoded",
    )
    prompt = AgentMessagePrompt(state=dummy_state, step_info=dummy_step_info)
    human_message = prompt.get_user_message(use_vision=True)
    assert isinstance(human_message, HumanMessage)
    assert isinstance(human_message.content, list)
    assert len(human_message.content) == 2
    text_part = human_message.content[0]
    image_part = human_message.content[1]
    assert isinstance(text_part, dict)
    assert text_part.get("type") == "text"
    state_text = text_part.get("text")
    assert "http://test.com" in state_text
    assert "<div>Test Interactive Element</div>" in state_text
    assert "Current step: 1/3" in state_text
    assert isinstance(image_part, dict)
    assert image_part.get("type") == "image_url"
    image_url_dict = image_part.get("image_url")
    assert isinstance(image_url_dict, dict)
    expected_url = "data:image/png;base64,fake_base64encoded"
    assert image_url_dict.get("url") == expected_url


class DummyActionResult(ActionResult):

    def __init__(self, extracted_content: str = "", error: str = ""):
        super().__init__(extracted_content=extracted_content, error=error)


def test_agent_message_prompt_without_screenshot_with_result():
    """
    Test AgentMessagePrompt.get_user_message for a scenario without a screenshot (vision off)
    and with action results having extracted content and error.
    Ensures that the function returns a HumanMessage with string content that includes the action results.
    """
    dummy_element_tree = DummyElementTree()
    dummy_step_info = DummyStepInfo(step_number=1, max_steps=5)
    dummy_state = DummyBrowserState(
        url="http://test.com/no_screenshot",
        tabs="TabA, TabB",
        element_tree=dummy_element_tree,
        pixels_above=0,
        pixels_below=0,
        screenshot=None,
    )
    dummy_result = [
        DummyActionResult(
            extracted_content="dummy extraction", error="dummy error occurred"
        )
    ]
    prompt = AgentMessagePrompt(
        state=dummy_state, result=dummy_result, step_info=dummy_step_info
    )
    human_message = prompt.get_user_message(use_vision=False)
    assert isinstance(human_message, HumanMessage)
    assert isinstance(human_message.content, str)
    content = human_message.content
    assert "http://test.com/no_screenshot" in content
    assert "<div>Test Interactive Element</div>" in content
    assert "Current step: 2/5" in content
    assert "dummy extraction" in content
    assert "dummy error occurred" in content


def test_planner_prompt_system_message():
    """
    Test that PlannerPrompt.get_system_message returns a SystemMessage whose content
    includes planning agent instructions in the expected JSON format.
    """
    planner_prompt = PlannerPrompt(
        action_description="Sample Action Description for planning",
        max_actions_per_step=5,
    )
    system_message = planner_prompt.get_system_message()
    assert isinstance(system_message, SystemMessage)
    content = system_message.content
    assert "planning agent" in content
    assert "state_analysis" in content
    assert "progress_evaluation" in content
    assert "challenges" in content
    assert "next_steps" in content
    assert "reasoning" in content


def test_system_prompt_get_system_message():
    """
    Test that SystemPrompt.get_system_message returns a SystemMessage with expected content.
    Verifies that the system message includes correct agent instructions,
    the default action description, and the max actions parameter.
    """
    action_description = "Dummy Action for Testing"
    max_actions = 7
    sys_prompt = SystemPrompt(
        action_description=action_description, max_actions_per_step=max_actions
    )
    system_message = sys_prompt.get_system_message()
    assert isinstance(system_message, SystemMessage)
    content = system_message.content
    assert "You are a precise browser automation agent" in content
    assert "Functions:" in content
    assert action_description in content
    expected_max_actions_line = f"use maximum {max_actions} actions per sequence"
    assert expected_max_actions_line in content


class RecordingElementTree:

    def __init__(self):
        self.last_include_attributes = None

    def clickable_elements_to_string(self, include_attributes):
        self.last_include_attributes = include_attributes
        return "<div>Recorded Element</div>"


def test_agent_message_prompt_include_attributes():
    """
    Test that AgentMessagePrompt.get_user_message correctly passes include_attributes
    to the element tree's clickable_elements_to_string method.
    """
    recording_element_tree = RecordingElementTree()
    dummy_step_info = DummyStepInfo(step_number=2, max_steps=4)
    dummy_state = DummyBrowserState(
        url="http://example.com/include_attributes",
        tabs="Main, Secondary",
        element_tree=recording_element_tree,
        pixels_above=10,
        pixels_below=20,
        screenshot=None,
    )
    custom_attributes = ["class", "data-test", "id"]
    prompt = AgentMessagePrompt(
        state=dummy_state,
        result=None,
        include_attributes=custom_attributes,
        step_info=dummy_step_info,
    )
    human_message = prompt.get_user_message(use_vision=False)
    assert isinstance(human_message, HumanMessage)
    assert isinstance(human_message.content, str)
    assert recording_element_tree.last_include_attributes == custom_attributes
    state_text = human_message.content
    assert "http://example.com/include_attributes" in state_text
    assert "<div>Recorded Element</div>" in state_text
    assert "Current step: 3/4" in state_text
