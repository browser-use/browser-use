import datetime
import pytest
from collections import namedtuple
from unittest.mock import MagicMock
from types import SimpleNamespace

from langchain_core.messages import HumanMessage, SystemMessage
from browser_use.agent.prompts import AgentMessagePrompt, SystemPrompt

# Try to import BrowserState; if not available, use a mock.
try:
    from browser_use.browser.views import BrowserState
except ImportError:
    BrowserState = MagicMock()

# Also import AgentStepInfo and ActionResult from the module.
try:
    from browser_use.agent.views import AgentStepInfo, ActionResult
except ImportError:
    AgentStepInfo = namedtuple("AgentStepInfo", ["step_number", "max_steps"])
    ActionResult = object  # dummy

# Define a dummy element tree to simulate clickable_elements_to_string.
class DummyElementTree:
    def clickable_elements_to_string(self, include_attributes):
        # Return an empty string simulating a page with no interactive elements.
        return ""

# Create a dummy BrowserState that satisfies the required constructor arguments.
class DummyBrowserState(BrowserState):
    def __init__(self, url, tabs, title, element_tree, selector_map, screenshot, pixels_above, pixels_below):
        self.url = url
        self.tabs = tabs
        self.title = title
        self.element_tree = element_tree
        self.selector_map = selector_map
        self.screenshot = screenshot
        self.pixels_above = pixels_above
        self.pixels_below = pixels_below

def test_agent_message_prompt_get_user_message_with_screenshot():
    """
    Test get_user_message of AgentMessagePrompt with a screenshot provided.
    This test creates a dummy BrowserState with all required attributes.
    When use_vision is True and a screenshot exists, the returned HumanMessage's 
    content should be a list containing both text and image components.
    """
    dummy_state = DummyBrowserState(
        url="http://example.com",
        tabs=["tab1"],
        title="Test Page",
        element_tree=DummyElementTree(),
        selector_map={},
        screenshot="dummy_base64data",
        pixels_above=0,
        pixels_below=0
    )
    dummy_step_info = AgentStepInfo(step_number=0, max_steps=1)
    amp = AgentMessagePrompt(state=dummy_state, step_info=dummy_step_info)
    user_msg = amp.get_user_message(use_vision=True)
    assert isinstance(user_msg, HumanMessage)
    assert isinstance(user_msg.content, list)
    text_items = [
        item for item in user_msg.content
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    assert len(text_items) > 0
    image_items = [
        item for item in user_msg.content
        if isinstance(item, dict) and item.get("type") == "image_url"
    ]
    assert len(image_items) > 0
    expected_url_prefix = "data:image/png;base64,dummy_base64data"
    image_url = image_items[0].get("image_url", {}).get("url", "")
    assert image_url.startswith(expected_url_prefix)

# Define a dummy element tree that returns a non-empty string to simulate interactive elements.
class DummyElementTreeNonEmpty:
    def clickable_elements_to_string(self, include_attributes):
        return "<button>Click Me</button>"

# Define a dummy BrowserState for when a screenshot is NOT provided.
class DummyBrowserStateNonScreenshot(BrowserState):
    def __init__(self, url, tabs, title, element_tree, selector_map, screenshot, pixels_above, pixels_below):
        self.url = url
        self.tabs = tabs
        self.title = title
        self.element_tree = element_tree
        self.selector_map = selector_map
        self.screenshot = screenshot
        self.pixels_above = pixels_above
        self.pixels_below = pixels_below

def test_agent_message_prompt_without_screenshot_with_results_and_elements():
    """
    Test get_user_message of AgentMessagePrompt when there is no screenshot provided,
    interactive elements are present, and action results (with extracted content and error) are provided.
    The returned HumanMessage content should be a string that includes all the expected information such as:
     - Interactive element details with proper pagination markers.
     - Current URL and tab details.
     - Appended action result information (both extracted content and error).
     - Date and time appended to the step information.
    """
    dummy_state = DummyBrowserStateNonScreenshot(
        url="http://example.com/test",
        tabs=["main", "settings"],
        title="Test Page",
        element_tree=DummyElementTreeNonEmpty(),
        selector_map={},
        screenshot=None,
        pixels_above=100,
        pixels_below=50,
    )
    dummy_result_obj = SimpleNamespace(
        extracted_content="Content extracted successfully",
        error="An unexpected error occurred during extraction."
    )
    amp = AgentMessagePrompt(state=dummy_state, result=[dummy_result_obj], step_info=None)
    message = amp.get_user_message(use_vision=True)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str)
    content = message.content
    assert "<button>Click Me</button>" in content
    assert "100 pixels above" in content
    assert "50 pixels below" in content
    assert "http://example.com/test" in content
    assert "main" in content and "settings" in content
    assert "Content extracted successfully" in content
    assert "unexpected error" in content
    assert "Current date and time:" in content

def test_system_prompt_get_system_message():
    """
    Test SystemPrompt.get_system_message returns a SystemMessage containing the expected sections.
    This includes checking for the INPUT STRUCTURE, RESPONSE FORMAT rules, the default action description,
    and the maximum actions per sequence string.
    """
    action_description = "Function actions: done, click_element, input_text"
    max_actions = 7
    sp = SystemPrompt(action_description, max_actions_per_step=max_actions)
    sys_msg = sp.get_system_message()
    assert isinstance(sys_msg, SystemMessage)
    content = sys_msg.content
    assert "INPUT STRUCTURE:" in content
    assert "RESPONSE FORMAT:" in content
    assert action_description in content
    assert f"use maximum {max_actions} actions per sequence" in content

# Additional tests.
class DummyElementTreeText:
    def clickable_elements_to_string(self, include_attributes):
        return "[Dummy Element Info]"

class DummyBrowserStateWithScreenshot(BrowserState):
    def __init__(self, url, tabs, title, element_tree, selector_map, screenshot, pixels_above, pixels_below):
        self.url = url
        self.tabs = tabs
        self.title = title
        self.element_tree = element_tree
        self.selector_map = selector_map
        self.screenshot = screenshot
        self.pixels_above = pixels_above
        self.pixels_below = pixels_below

def test_agent_message_prompt_use_vision_false_with_screenshot():
    """
    Test get_user_message of AgentMessagePrompt returns a plain text string 
    when use_vision is False, even if a screenshot is provided.
    This ensures that the image component is omitted when the vision flag is off.
    """
    dummy_state = DummyBrowserStateWithScreenshot(
        url="http://test.com",
        tabs=["main"],
        title="Test with Screenshot but no Vision",
        element_tree=DummyElementTreeText(),
        selector_map={},
        screenshot="base64imagedata",
        pixels_above=10,
        pixels_below=20
    )
    amp = AgentMessagePrompt(state=dummy_state, step_info=None)
    message = amp.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str)
    assert "data:image/png;base64" not in message.content
    assert "http://test.com" in message.content
    assert "[Dummy Element Info]" in message.content
    # Check that pixels information is included in some form.
    assert "10 pixels above" in message.content or "pixels above" in message.content
    assert "20 pixels below" in message.content or "pixels below" in message.content

def test_agent_message_prompt_long_error_truncation():
    """
    Test that AgentMessagePrompt properly truncates a long error message.
    When a result's error message is longer than max_error_length, only the last
    max_error_length characters (preceded by an ellipsis) are included in the output.
    """
    # Create a long error message of 500 characters.
    long_error = "E" * 500
    truncated_error = long_error[-400:]
    dummy_state = DummyBrowserStateNonScreenshot(
         url="http://dummy.com",
         tabs=["tab1"],
         title="Dummy page",
         element_tree=DummyElementTreeNonEmpty(),
         selector_map={},
         screenshot=None,
         pixels_above=0,
         pixels_below=0
    )
    dummy_result_obj = SimpleNamespace(
         extracted_content="",
         error=long_error
    )
    amp = AgentMessagePrompt(state=dummy_state, result=[dummy_result_obj], step_info=None, max_error_length=400)
    message = amp.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str)
    expected_error_output = "..." + truncated_error
    assert expected_error_output in message.content

# Dummy element tree that returns an empty string to simulate no interactive elements.
class DummyElementTreeEmpty:
    def clickable_elements_to_string(self, include_attributes):
        return ""

# Dummy BrowserState for an empty page, no screenshot.
class DummyBrowserStateEmpty(BrowserState):
    def __init__(self, url, tabs, title, element_tree, selector_map, screenshot, pixels_above, pixels_below):
        self.url = url
        self.tabs = tabs
        self.title = title
        self.element_tree = element_tree
        self.selector_map = selector_map
        self.screenshot = screenshot
        self.pixels_above = pixels_above
        self.pixels_below = pixels_below

def test_agent_message_prompt_empty_page_no_screenshot():
    """
    Test get_user_message of AgentMessagePrompt when the interactive elements are empty,
    no screenshot is available, and use_vision is False.
    The output should be a plain text string that indicates 'empty page' for the interactive elements.
    """
    dummy_state = DummyBrowserStateEmpty(
        url="http://empty.com",
        tabs=["only_tab"],
        title="Empty Page",
        element_tree=DummyElementTreeEmpty(),
        selector_map={},
        screenshot=None,
        pixels_above=0,
        pixels_below=0
    )
    amp = AgentMessagePrompt(state=dummy_state, step_info=None)
    message = amp.get_user_message(use_vision=False)
    # Expecting a plain text string, not a list.
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str)
    # Check that the empty page text is included.
    assert "empty page" in message.content
    # Check that the URL is included.
    assert "http://empty.com" in message.content
    # Check that it does not include image data.
    assert "data:image/png;base64" not in message.content
