import pytest
from browser_use.agent.message_manager.views import MessageHistory, MessageMetadata
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

def test_remove_message_at_index():
    """
    Test the removal of messages at a specific index.
    This test adds two messages to the MessageHistory, then removes the message at index 0.
    It verifies that MessageHistory updates its total_tokens and messages list correctly both
    when removing a message at a given index and when using the default index (-1).
    """
    history = MessageHistory()
    msg1 = HumanMessage(content="Hello")
    meta1 = MessageMetadata(input_tokens=10)
    msg2 = AIMessage(content="Hi there!")
    meta2 = MessageMetadata(input_tokens=15)
    history.add_message(msg1, meta1)
    history.add_message(msg2, meta2)
    
    assert history.total_tokens == 25
    assert len(history.messages) == 2
    
    history.remove_message(index=0)
    assert len(history.messages) == 1
    assert history.total_tokens == 15
    remaining_message = history.messages[0].message
    assert isinstance(remaining_message, AIMessage)
    
    history.remove_message()
    assert len(history.messages) == 0
    assert history.total_tokens == 0

def test_remove_message_empty_history():
    """
    Test removing a message from an empty MessageHistory.
    This test verifies that calling remove_message on an empty history
    does not alter total_tokens or the messages list, and no error is raised.
    """
    history = MessageHistory()
    assert len(history.messages) == 0
    assert history.total_tokens == 0
    history.remove_message()
    assert len(history.messages) == 0
    assert history.total_tokens == 0

def test_remove_middle_message():
    """
    Test removing a message from the middle of the MessageHistory.
    This test adds three messages, then removes the message at index 1.
    It verifies that the correct message is removed, the total_tokens
    are updated accordingly, and the remaining messages maintain the proper order.
    """
    history = MessageHistory()
    msg1 = HumanMessage(content="Message One")
    meta1 = MessageMetadata(input_tokens=5)
    msg2 = AIMessage(content="Message Two")
    meta2 = MessageMetadata(input_tokens=7)
    msg3 = HumanMessage(content="Message Three")
    meta3 = MessageMetadata(input_tokens=8)
    
    history.add_message(msg1, meta1)
    history.add_message(msg2, meta2)
    history.add_message(msg3, meta3)
    
    assert history.total_tokens == (5 + 7 + 8)
    assert len(history.messages) == 3
    
    history.remove_message(index=1)
    assert len(history.messages) == 2
    assert history.total_tokens == (5 + 8)
    
    remaining_message_1 = history.messages[0].message
    remaining_message_2 = history.messages[1].message
    assert isinstance(remaining_message_1, HumanMessage)
    assert remaining_message_1.content == "Message One"
    assert isinstance(remaining_message_2, HumanMessage)
    assert remaining_message_2.content == "Message Three"

def test_remove_message_invalid_index():
    """
    Test that attempting to remove a message using an invalid index (out-of-range) raises an IndexError.
    This ensures that the MessageHistory.remove_message method behaves as expected when given an index not present in the messages list.
    """
    history = MessageHistory()
    # Add one message to the history.
    message = HumanMessage(content="Test Message")
    metadata = MessageMetadata(input_tokens=5)
    history.add_message(message, metadata)
    
    # Attempt removal with an invalid positive index (valid indices are only 0 or -1).
    with pytest.raises(IndexError):
        history.remove_message(index=1)  # Only index 0 (or -1) is valid.
    
    # Attempt removal with an invalid negative index (for one element, only -1 is valid).
    with pytest.raises(IndexError):
        history.remove_message(index=-2)
