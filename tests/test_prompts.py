import pytest
from types import SimpleNamespace
from datetime import datetime
from browser_use.agent.prompts import AgentMessagePrompt, SystemPrompt, PlannerPrompt
from langchain_core.messages import HumanMessage, SystemMessage
from browser_use.agent.prompts import AgentMessagePrompt
from langchain_core.messages import HumanMessage

# No additional imports required for this test.
def test_agent_message_prompt_with_screenshot():
    """
    Test AgentMessagePrompt.get_user_message to verify it returns a vision-enabled 
    HumanMessage with both text and image data when a screenshot is provided.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy clickable element"
    dummy_state = SimpleNamespace(
        url="http://example.com",
        tabs=["http://example.com", "http://example.org"],
        element_tree=DummyElementTree(),
        pixels_above=50,
        pixels_below=100,
        screenshot="fake_base64_image_string"
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=True)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, list)
    assert len(message.content) == 2
    text_item = message.content[0]
    image_item = message.content[1]
    assert isinstance(text_item, dict)
    assert text_item.get("type") == "text"
    assert "http://example.com" in text_item.get("text")
    assert isinstance(image_item, dict)
    assert image_item.get("type") == "image_url"
    image_url_info = image_item.get("image_url")
    assert isinstance(image_url_info, dict)
    assert "fake_base64_image_string" in image_url_info.get("url")
def test_agent_message_prompt_without_screenshot():
    """
    Test AgentMessagePrompt.get_user_message to verify that when there is no screenshot 
    (or use_vision is False), the HumanMessage is returned with plain text content and no image element.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy clickable element with no screenshot"
    dummy_state = SimpleNamespace(
        url="http://noscreenshot.com",
        tabs=["http://noscreenshot.com"],
        element_tree=DummyElementTree(),
        pixels_above=0,
        pixels_below=0,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str)
    assert "Current url: http://noscreenshot.com" in message.content
    assert "dummy clickable element with no screenshot" in message.content
def test_agent_message_prompt_with_step_info_and_result():
    """
    Test that when step_info and result are provided, the returned message includes 
    the appropriate step info, action results, and error messages.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy element info"
    dummy_state = SimpleNamespace(
        url="http://teststep.com",
        tabs=["http://teststep.com"],
        element_tree=DummyElementTree(),
        pixels_above=20,
        pixels_below=20,
        screenshot=None
    )
    dummy_result1 = SimpleNamespace(extracted_content="info1", error=None)
    dummy_result2 = SimpleNamespace(extracted_content=None, error="error_info2")
    results = [dummy_result1, dummy_result2]
    dummy_step_info = SimpleNamespace(step_number=2, max_steps=5)
    prompt = AgentMessagePrompt(state=dummy_state, result=results, step_info=dummy_step_info)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str)
    assert "dummy element info" in message.content
    assert "http://teststep.com" in message.content
    assert "Action result 1/2: info1" in message.content
    assert "Action error 2/2:" in message.content and "error_info2" in message.content
    assert "Current step: 3/5" in message.content
    assert "Current date and time:" in message.content
def test_planner_prompt_system_message():
    """
    Test PlannerPrompt.get_system_message ensures that the returned SystemMessage
    contains planning instructions and the expected JSON keys.
    """
    planner = PlannerPrompt(action_description="dummy action")
    msg = planner.get_system_message()
    assert isinstance(msg, SystemMessage)
    content = msg.content
    assert "planning agent" in content.lower(), "The message should indicate that this is a planning agent."
    required_keys = [
        '"state_analysis":',
        '"progress_evaluation":',
        '"challenges":',
        '"next_steps":',
        '"reasoning":'
    ]
    for key in required_keys:
        assert key in content, f"Missing expected key in the PlannerPrompt message: {key}"
def test_agent_message_prompt_error_truncation():
    """
    Test that AgentMessagePrompt.get_user_message correctly truncates the error message
    in the action result using the max_error_length property.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy element info for error truncation test"
    dummy_state = SimpleNamespace(
        url="http://errortruncation.com",
        tabs=["http://errortruncation.com"],
        element_tree=DummyElementTree(),
        pixels_above=0,
        pixels_below=0,
        screenshot=None
    )
    error_text = "abcdefghijklmnop"  # 16 characters long
    max_error_length = 10
    truncated_error = error_text[-max_error_length:]  # expected: "ghijklmnop"
    dummy_result = SimpleNamespace(extracted_content=None, error=error_text)
    results = [dummy_result]
    prompt = AgentMessagePrompt(state=dummy_state, result=results, step_info=None, max_error_length=max_error_length)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    content = message.content
    assert f"...{truncated_error}" in content, "The error message was not correctly truncated."
    assert "Action error 1/1:" in content
def test_system_prompt_important_rules():
    """
    Test that SystemPrompt.important_rules returns a string containing the maximum number 
    of actions per sequence as specified during initialization.
    """
    max_actions = 5
    action_description = "dummy action description"
    prompt = SystemPrompt(action_description=action_description, max_actions_per_step=max_actions)
    rules_text = prompt.important_rules()
    expected_string = f"use maximum {max_actions} actions per sequence"
    assert expected_string in rules_text, f"Expected '{expected_string}' to be in the rules text, got: {rules_text}"
def test_system_prompt_get_system_message():
    """
    Test that SystemPrompt.get_system_message returns a SystemMessage that includes:
    - The agent instructions with 'You are a precise browser automation agent'
    - The input format description (e.g., 'INPUT STRUCTURE:')
    - The important rules (e.g., 'RESPONSE FORMAT:' and the max action limit)
    - The default action description under the Functions section.
    """
    action_description = "dummy action description"
    max_actions = 8
    prompt = SystemPrompt(action_description=action_description, max_actions_per_step=max_actions)
    sys_msg = prompt.get_system_message()
    assert isinstance(sys_msg, SystemMessage)
    content = sys_msg.content
    assert "You are a precise browser automation agent" in content
    assert "INPUT STRUCTURE:" in content
    assert "RESPONSE FORMAT:" in content
    assert action_description in content
    assert f"use maximum {max_actions} actions per sequence" in content
def test_agent_message_prompt_include_attributes():
    """
    Test that AgentMessagePrompt.get_user_message correctly passes the include_attributes parameter to the 
    element_tree's clickable_elements_to_string method.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return f'Attributes: {", ".join(include_attributes)}' if include_attributes else "no attributes"
    dummy_state = SimpleNamespace(
        url="http://includeattributes.com",
        tabs=["http://includeattributes.com"],
        element_tree=DummyElementTree(),
        pixels_above=0,
        pixels_below=0,
        screenshot=None
    )
    include_attrs = ["data-test", "placeholder"]
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None, include_attributes=include_attrs)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str)
    assert "Attributes: data-test, placeholder" in message.content
def test_agent_message_prompt_empty_page():
    """
    Test AgentMessagePrompt.get_user_message for a scenario where the clickable_elements_to_string
    returns an empty string, resulting in an "empty page" output.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return ""
    dummy_state = SimpleNamespace(
        url="http://emptytest.com",
        tabs=["http://emptytest.com"],
        element_tree=DummyElementTree(),
        pixels_above=0,
        pixels_below=0,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str)
    assert "Interactive elements from current page:\nempty page" in message.content
    assert "Current url: http://emptytest.com" in message.content
    assert "[Task history memory ends here]" in message.content
    assert "['http://emptytest.com']" in message.content
def test_agent_message_prompt_pixels_logic():
    """
    Test that AgentMessagePrompt.get_user_message correctly formats the interactive elements when there is
    no content above (pixels_above=0) but content exists below (pixels_below>0).
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "element A"
    dummy_state = SimpleNamespace(
        url="http://testpixels.com",
        tabs=["http://testpixels.com"],
        element_tree=DummyElementTree(),
        pixels_above=0,
        pixels_below=80,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    content = message.content
    assert "[Start of page]" in content, "Expected a start page marker because pixels_above is 0."
    assert "element A" in content, "Interactive elements information should be included."
    assert "80 pixels below" in content, "Expected a footer indicating additional content below."
    assert "[End of page]" not in content, "The '[End of page]' marker should not appear when pixels_below is provided."
def test_agent_message_prompt_with_combined_extracted_and_error():
    """
    Test AgentMessagePrompt.get_user_message for a scenario where a single result has both extracted_content 
    and error provided, verifying that both pieces are appended correctly.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy interactive elements"
    dummy_state = SimpleNamespace(
        url="http://combinedinfo.com",
        tabs=["http://combinedinfo.com"],
        element_tree=DummyElementTree(),
        pixels_above=10,
        pixels_below=10,
        screenshot=None
    )
    dummy_result = SimpleNamespace(extracted_content="combined info", error="complete error message")
    results = [dummy_result]
    prompt = AgentMessagePrompt(state=dummy_state, result=results, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    content = message.content
    assert "Action result 1/1: combined info" in content, "The extracted content should be included in the output."
    assert "Action error 1/1: ...complete error message" in content, "The error message should be included with proper formatting."
def test_agent_message_prompt_pixels_above_only():
    """
    Test AgentMessagePrompt.get_user_message when there is content above (pixels_above > 0) 
    and no content below (pixels_below == 0). This verifies the inclusion of a top scroll message 
    and the presence of the '[End of page]' marker.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "element with above only"
    dummy_state = SimpleNamespace(
        url="http://aboveonly.com",
        tabs=["http://aboveonly.com"],
        element_tree=DummyElementTree(),
        pixels_above=30,
        pixels_below=0,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str)
    expected_top_message = "... 30 pixels above - scroll or extract content to see more ..."
    assert expected_top_message in message.content, "Expected top scroll message to be included."
    assert "[End of page]" in message.content, "Expected '[End of page]' marker to be included in the output."
    assert "element with above only" in message.content
def test_agent_message_prompt_use_vision_true_without_screenshot():
    """
    Test that AgentMessagePrompt.get_user_message returns a plain text HumanMessage even when use_vision is True,
    if no screenshot is provided.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy clickable element without screenshot"
    dummy_state = SimpleNamespace(
        url="http://noscreenshot-vision.com",
        tabs=["http://noscreenshot-vision.com"],
        element_tree=DummyElementTree(),
        pixels_above=0,
        pixels_below=0,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=True)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str), "Expected plain text output when no screenshot is provided, even if use_vision is True."
    assert "Current url: http://noscreenshot-vision.com" in message.content
    assert "dummy clickable element without screenshot" in message.content
def test_system_prompt_input_format():
    """
    Test that SystemPrompt.input_format returns a properly formatted string containing
    the browser input structure instructions, such as the current URL, available tabs,
    interactive element description, example, and notes.
    """
    prompt = SystemPrompt(action_description="dummy action description")
    input_format_text = prompt.input_format()
    assert "INPUT STRUCTURE:" in input_format_text, "Missing 'INPUT STRUCTURE:' header."
    assert "1. Current URL: The webpage you're currently on" in input_format_text, "Missing current URL description."
    assert "2. Available Tabs:" in input_format_text, "Missing available tabs description."
    assert "Interactive Elements:" in input_format_text, "Missing interactive elements description."
    assert "Example:" in input_format_text, "Missing example section."
    assert "Notes:" in input_format_text, "Missing notes section."
def test_agent_message_prompt_with_none_pixels():
    """
    Test that AgentMessagePrompt.get_user_message correctly handles the case
    when pixels_above and pixels_below are None. The function should treat them as 0,
    displaying the '[Start of page]' and '[End of page]' markers appropriately.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy element from page"
    dummy_state = SimpleNamespace(
        url="http://nonumericpixels.com",
        tabs=["http://nonumericpixels.com"],
        element_tree=DummyElementTree(),
        pixels_above=None,
        pixels_below=None,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    content = message.content
    assert "[Start of page]" in content, "Expected '[Start of page]' marker when pixels_above is None (treated as 0)."
    assert "[End of page]" in content, "Expected '[End of page]' marker when pixels_below is None (treated as 0)."
    assert "dummy element from page" in content, "Expected the element text to be included in the output."
    assert "http://nonumericpixels.com" in content, "Expected the URL to be displayed."
def test_agent_message_prompt_with_screenshot_but_use_vision_false():
    """
    Test that AgentMessagePrompt.get_user_message returns a plain text HumanMessage (a string)
    even if a screenshot is provided, when use_vision is set to False.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "element with screenshot but use_vision false"
    dummy_state = SimpleNamespace(
        url="http://screenshotbutfalse.com",
        tabs=["http://screenshotbutfalse.com"],
        element_tree=DummyElementTree(),
        pixels_above=10,
        pixels_below=10,
        screenshot="valid_base64_string"
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str)
    assert "http://screenshotbutfalse.com" in message.content
    assert "element with screenshot but use_vision false" in message.content
    assert "valid_base64_string" not in message.content
def test_agent_message_prompt_empty_screenshot_returns_text():
    """
    Test that AgentMessagePrompt.get_user_message returns a plain text HumanMessage 
    when the screenshot is an empty string, even if use_vision is True.
    This ensures that an empty screenshot value is treated as falsy and does not trigger the vision mode.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy clickable element for empty screenshot test"
    dummy_state = SimpleNamespace(
        url="http://emptyscreenshot.com",
        tabs=["http://emptyscreenshot.com"],
        element_tree=DummyElementTree(),
        pixels_above=0,
        pixels_below=0,
        screenshot=""
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=True)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, str), "Expected plain text content when screenshot is empty."
    assert "http://emptyscreenshot.com" in message.content
    assert "dummy clickable element for empty screenshot test" in message.content
def test_agent_message_prompt_empty_tabs():
    """
    Test that AgentMessagePrompt.get_user_message handles the scenario when the tabs list is empty.
    The output should reflect an empty tabs list in the state description.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy clickable element for empty tabs test"
    dummy_state = SimpleNamespace(
        url="http://emptytabs.com",
        tabs=[],  # empty tabs list
        element_tree=DummyElementTree(),
        pixels_above=5,
        pixels_below=5,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    content = message.content
    assert "Available tabs:" in content, "Expected to see Available tabs in the output."
    assert "[]" in content, "Expected output to show an empty tabs list."
def test_agent_message_prompt_with_empty_result_list():
    """
    Test that AgentMessagePrompt.get_user_message returns a plain text HumanMessage when an empty result list is provided,
    ensuring that no action result or error messages appear in the output.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy element with empty result list"
    dummy_state = SimpleNamespace(
        url="http://emptyresult.com",
        tabs=["http://emptyresult.com"],
        element_tree=DummyElementTree(),
        pixels_above=0,
        pixels_below=0,
        screenshot=None
    )
    # Provide an empty list for result rather than None.
    prompt = AgentMessagePrompt(state=dummy_state, result=[], step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    content = message.content
    # Check that no action result or error messages are added to the state description.
    assert "Action result" not in content, "Expected no action result messages for empty result list."
    assert "Action error" not in content, "Expected no action error messages for empty result list."
def test_agent_message_prompt_with_whitespace_elements():
    """
    Test that AgentMessagePrompt.get_user_message correctly handles the scenario where 
    the clickable_elements_to_string method returns a whitespace string instead of an empty string.
    In this case, the output should include the whitespace as returned by the element tree and should not be replaced with "empty page".
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "   "  # whitespace string
    
    dummy_state = SimpleNamespace(
        url="http://whitespace.com",
        tabs=["http://whitespace.com"],
        element_tree=DummyElementTree(),
        pixels_above=0,
        pixels_below=0,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    
    # Assert that the message is a plain text HumanMessage.
    assert isinstance(message, HumanMessage)
    content = message.content
    # The output should include the whitespace string returned by the element tree.
    assert "   " in content, "Expected the whitespace string to be present in the message content."
    # Also ensure that the text 'empty page' was not added.
    assert "empty page" not in content, "The message content should not be replaced with 'empty page' when non-empty whitespace is returned."
def test_agent_message_prompt_with_screenshot_and_step_info():
    """
    Test that AgentMessagePrompt.get_user_message returns a vision-enabled HumanMessage with both text and image data
    when a screenshot and step info are provided, and that the step info (current step and maximum steps) is correctly included.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "Dummy element content"
    dummy_state = SimpleNamespace(
        url="http://screenshot-step.com",
        tabs=["http://screenshot-step.com"],
        element_tree=DummyElementTree(),
        pixels_above=10,
        pixels_below=10,
        screenshot="base64_image_data"
    )
    # step_number is zero-indexed in the prompt: step_number + 1 is displayed.
    dummy_step_info = SimpleNamespace(step_number=4, max_steps=10)
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=dummy_step_info)
    message = prompt.get_user_message(use_vision=True)
    # Assert that the message has vision enabled (i.e., it's a list with text and image items)
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, list)
    assert len(message.content) == 2
    text_item = message.content[0]
    image_item = message.content[1]
    # Verify that the step info is correctly included, step_number: 4 yields "Current step: 5/10"
    assert "Current step: 5/10" in text_item.get("text"), "Step info was not correctly included in the message text."
    # Verify that the image element includes the provided screenshot
    assert image_item.get("type") == "image_url"
    image_url_info = image_item.get("image_url")
    assert isinstance(image_url_info, dict)
    assert "base64_image_data" in image_url_info.get("url"), "Screenshot data not found in the image message."
def test_agent_message_prompt_with_negative_pixels():
    """
    Test AgentMessagePrompt.get_user_message handles negative pixel values.
    Negative values for pixels_above and pixels_below should be treated as 0,
    so the output should include the '[Start of page]' and '[End of page]' markers,
    and should not include any scroll messages indicating extra content.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "element negative"
    dummy_state = SimpleNamespace(
        url="http://negativetest.com",
        tabs=["http://negativetest.com"],
        element_tree=DummyElementTree(),
        pixels_above=-10,
        pixels_below=-20,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    # Ensure that we get a plain text HumanMessage
    assert isinstance(message, HumanMessage)
    content = message.content
    # Check for the start and end markers and absence of scroll messages caused by positive pixel counts.
    assert "[Start of page]" in content, "Expected '[Start of page]' marker when pixels_above is negative or 0."
    assert "[End of page]" in content, "Expected '[End of page]' marker when pixels_below is negative or 0."
    assert "scroll or extract content to see more" not in content, "Unexpected scroll message found for negative pixel values."
def test_agent_message_prompt_when_clickable_elements_returns_none():
    """
    Test that AgentMessagePrompt.get_user_message handles the case when clickable_elements_to_string 
    returns None. The output should include the string "None" as a result of converting None to a string.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            # Simulate a scenario where the element tree returns None instead of a string.
            return None
    dummy_state = SimpleNamespace(
        url="http://noneelements.com",
        tabs=["http://noneelements.com"],
        element_tree=DummyElementTree(),
        pixels_above=10,
        pixels_below=5,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    content = message.content
    # Since None is not an empty string, it will be concatenated and converted to "None"
    assert "None" in content, "Expected 'None' to appear in the content when clickable_elements_to_string returns None."
def test_agent_message_prompt_with_blank_screenshot():
    """
    Test that AgentMessagePrompt.get_user_message returns a vision-enabled HumanMessage with both text and image data 
    when the screenshot is a non-empty whitespace string.
    """
    # Create a dummy element tree that returns a fixed string.
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "test element content"
    
    # Set up a dummy state where screenshot is a non-empty whitespace string ("   ").
    dummy_state = SimpleNamespace(
        url="http://blank-screenshot.com",
        tabs=["http://blank-screenshot.com"],
        element_tree=DummyElementTree(),
        pixels_above=5,
        pixels_below=5,
        screenshot="   "  # non-empty whitespace string; should be treated as truthy
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=True)
    
    # The output should be a vision-enabled HumanMessage with content as a list of two items
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, list), "Expected vision-enabled message with list content."
    assert len(message.content) == 2, "Expected two items in the content: text and image."
    
    text_item = message.content[0]
    image_item = message.content[1]
    
    # Verify the text item
    assert isinstance(text_item, dict)
    assert text_item.get("type") == "text"
    assert "http://blank-screenshot.com" in text_item.get("text"), "The URL should appear in the text message."
    
    # Verify the image item
    assert isinstance(image_item, dict)
    assert image_item.get("type") == "image_url"
    image_url_info = image_item.get("image_url")
    assert isinstance(image_url_info, dict)
    # The image URL should include the whitespace screenshot string
    assert "   " in image_url_info.get("url"), "Expected the whitespace screenshot to be included in the image URL."
def test_agent_message_prompt_with_none_tabs():
    """
    Test that AgentMessagePrompt.get_user_message correctly handles the case when the state's tabs attribute is None.
    The output should include the string 'None' in the 'Available tabs:' section.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy clickable content"
    dummy_state = SimpleNamespace(
        url="http://nonetabs.com",
        tabs=None,  # tabs is None
        element_tree=DummyElementTree(),
        pixels_above=0,
        pixels_below=0,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    assert isinstance(message, HumanMessage)
    content = message.content
    # Check that the 'Available tabs:' section is present with the string "None"
    assert "Available tabs:" in content
    assert "None" in content, "Expected 'None' to appear in the message when state.tabs is None"
def test_agent_message_prompt_invalid_pixels_types():
    """
    Test that AgentMessagePrompt.get_user_message raises a TypeError when pixels_above is not an integer.
    This simulates an unexpected type for pixel values.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy clickable element"
    # Setting pixels_above to a non-integer value should raise a TypeError during comparison.
    dummy_state = SimpleNamespace(
        url="http://invalidpixels.com",
        tabs=["http://invalidpixels.com"],
        element_tree=DummyElementTree(),
        pixels_above="not a number",  # This is not an integer.
        pixels_below=10,
        screenshot=None
    )
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    with pytest.raises(TypeError):
        prompt.get_user_message(use_vision=False)import pytest
from types import SimpleNamespace
from browser_use.agent.prompts import AgentMessagePrompt


def test_agent_message_prompt_with_float_pixels():
    """
    Test that AgentMessagePrompt.get_user_message correctly handles non-integer (float) pixel values
    for pixels_above and pixels_below, ensuring that the output includes appropriate scroll messages 
    with float values and does not include the '[End of page]' marker when pixels_below is provided.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy float element"
    
    dummy_state = SimpleNamespace(
        url="http://floatpixels.com",
        tabs=["http://floatpixels.com"],
        element_tree=DummyElementTree(),
        pixels_above=5.5,
        pixels_below=3.3,
        screenshot=None
    )
    
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    content = message.content
    
    # Assert that text contains the "[Start of page]" marker and clickable element info.
    assert "[Start of page]" in content, "Expected '[Start of page]' marker with float pixels."
    assert "dummy float element" in content, "Expected dummy float element text in the message."
    
    # Check that the scroll message for pixels_above shows a float value.
    assert f"... {dummy_state.pixels_above} pixels above - scroll or extract content to see more ..." in content, \
           "Expected correct float value displayed in the pixels_above scroll message."
    
    # Check that the scroll message for pixels_below shows a float value.
    assert f"... {dummy_state.pixels_below} pixels below - scroll or extract content to see more ..." in content, \
           "Expected correct float value displayed in the pixels_below scroll message."
    
    # Because pixels_below > 0, the "[End of page]" marker should not appear.
    assert "[End of page]" not in content, "Unexpected '[End of page]' marker when pixels_below is positive."
import pytest
from types import SimpleNamespace
from browser_use.agent.prompts import AgentMessagePrompt


def test_agent_message_prompt_with_float_pixels():
    """
    Test that AgentMessagePrompt.get_user_message correctly handles non-integer (float) pixel values
    for pixels_above and pixels_below. When pixels_above and pixels_below are positive floats, the
    output should include the appropriate scroll messages with the float values and should not contain
    the "[Start of page]" or "[End of page]" markers.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy float element"
    
    dummy_state = SimpleNamespace(
        url="http://floatpixels.com",
        tabs=["http://floatpixels.com"],
        element_tree=DummyElementTree(),
        pixels_above=5.5,
        pixels_below=3.3,
        screenshot=None
    )
    
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    content = message.content
    
    # Check that the scroll message for pixels_above shows the correct float value.
    scroll_message_above = f"... {dummy_state.pixels_above} pixels above - scroll or extract content to see more ..."
    assert scroll_message_above in content, "Expected correct float value scroll message for pixels_above."
    
    # Check that the scroll message for pixels_below shows the correct float value.
    scroll_message_below = f"... {dummy_state.pixels_below} pixels below - scroll or extract content to see more ..."
    assert scroll_message_below in content, "Expected correct float value scroll message for pixels_below."
    
    # Since pixels_above is positive, "[Start of page]" should not appear.
    assert "[Start of page]" not in content, "Did not expect '[Start of page]' marker when pixels_above is positive."
    
    # Because pixels_below is positive, the "[End of page]" marker should not appear.
    assert "[End of page]" not in content, "Unexpected '[End of page]' marker when pixels_below is positive."
import pytest
from types import SimpleNamespace
from browser_use.agent.prompts import AgentMessagePrompt


def test_agent_message_prompt_with_float_pixels():
    """
    Test that AgentMessagePrompt.get_user_message correctly handles non-integer (float) pixel values
    for pixels_above and pixels_below. When pixels_above and pixels_below are positive floats, the
    output should include the appropriate scroll messages with the float values and should not contain
    the "[Start of page]" or "[End of page]" markers.
    """
    class DummyElementTree:
        def clickable_elements_to_string(self, include_attributes):
            return "dummy float element"
    
    dummy_state = SimpleNamespace(
        url="http://floatpixels.com",
        tabs=["http://floatpixels.com"],
        element_tree=DummyElementTree(),
        pixels_above=5.5,
        pixels_below=3.3,
        screenshot=None
    )
    
    prompt = AgentMessagePrompt(state=dummy_state, result=None, step_info=None)
    message = prompt.get_user_message(use_vision=False)
    content = message.content
    
    # Check that the scroll message for pixels_above shows the correct float value.
    scroll_message_above = f"... {dummy_state.pixels_above} pixels above - scroll or extract content to see more ..."
    assert scroll_message_above in content, "Expected correct float value scroll message for pixels_above."
    
    # Check that the scroll message for pixels_below shows the correct float value.
    scroll_message_below = f"... {dummy_state.pixels_below} pixels below - scroll or extract content to see more ..."
    assert scroll_message_below in content, "Expected correct float value scroll message for pixels_below."
    
    # Since pixels_above is positive, "[Start of page]" should not appear.
    assert "[Start of page]" not in content, "Did not expect '[Start of page]' marker when pixels_above is positive."
    
    # Because pixels_below is positive, the "[End of page]" marker should not appear.
    assert "[End of page]" not in content, "Unexpected '[End of page]' marker when pixels_below is positive."
