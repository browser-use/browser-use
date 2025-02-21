import pytest
from browser_use.agent.message_manager.views import (
    MessageHistory,
    MessageMetadata,
)
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)


def test_insert_and_remove_message():
    """Test inserting a message at a given position and then removing messages updates the order and token totals correctly."""
    history = MessageHistory()
    msg1 = HumanMessage(content="first message")
    meta1 = MessageMetadata(input_tokens=3)
    history.add_message(msg1, meta1)
    msg3 = HumanMessage(content="third message")
    meta3 = MessageMetadata(input_tokens=4)
    history.add_message(msg3, meta3)
    msg2 = AIMessage(content="second message")
    meta2 = MessageMetadata(input_tokens=2)
    history.add_message(msg2, meta2, position=1)
    assert history.messages[0].message.content == "first message"
    assert history.messages[1].message.content == "second message"
    assert history.messages[2].message.content == "third message"
    assert history.total_tokens == 9
    history.remove_message(index=1)
    assert len(history.messages) == 2
    assert history.messages[0].message.content == "first message"
    assert history.messages[1].message.content == "third message"
    assert history.total_tokens == 7
    history.remove_message(index=0)
    history.remove_message(index=0)
    assert history.total_tokens == 0
    history.remove_message()
    assert history.total_tokens == 0


def test_remove_message_default_index():
    """Test that removing a message using default index (-1) removes the last message and updates token totals."""
    history = MessageHistory()
    msg1 = HumanMessage(content="message one")
    meta1 = MessageMetadata(input_tokens=1)
    msg2 = AIMessage(content="message two")
    meta2 = MessageMetadata(input_tokens=2)
    history.add_message(msg1, meta1)
    history.add_message(msg2, meta2)
    assert history.total_tokens == 3
    history.remove_message()
    assert len(history.messages) == 1
    assert history.messages[0].message.content == "message one"
    assert history.total_tokens == 1


def test_remove_message_invalid_index():
    """Test that calling remove_message with an invalid index on a non-empty history raises IndexError."""
    history = MessageHistory()
    msg1 = HumanMessage(content="test message")
    meta1 = MessageMetadata(input_tokens=5)
    history.add_message(msg1, meta1)
    with pytest.raises(IndexError):
        history.remove_message(index=5)


def test_insert_message_negative_position():
    """Test adding a message with a negative position value inserts the message in the correct order and updates token totals."""
    history = MessageHistory()
    message_A = HumanMessage(content="Message A")
    meta_A = MessageMetadata(input_tokens=5)
    message_B = HumanMessage(content="Message B")
    meta_B = MessageMetadata(input_tokens=10)
    history.add_message(message_A, meta_A)
    history.add_message(message_B, meta_B)
    message_C = AIMessage(content="Message C")
    meta_C = MessageMetadata(input_tokens=7)
    history.add_message(message_C, meta_C, position=-1)
    assert len(history.messages) == 3
    assert history.messages[0].message.content == "Message A"
    assert history.messages[1].message.content == "Message C"
    assert history.messages[2].message.content == "Message B"
    assert history.total_tokens == 22


def test_insert_message_out_of_range_positive_index():
    """
    Test adding a message with a position index greater than the history length.
    This verifies that the message is appended to the end and the token totals update correctly.
    """
    history = MessageHistory()
    msg1 = HumanMessage(content="Message 1")
    meta1 = MessageMetadata(input_tokens=1)
    history.add_message(msg1, meta1)
    msg2 = AIMessage(content="Message 2")
    meta2 = MessageMetadata(input_tokens=2)
    history.add_message(msg2, meta2)
    msg3 = SystemMessage(content="Message 3")
    meta3 = MessageMetadata(input_tokens=3)
    history.add_message(msg3, meta3, position=10)
    assert len(history.messages) == 3
    assert history.messages[0].message.content == "Message 1"
    assert history.messages[1].message.content == "Message 2"
    assert history.messages[2].message.content == "Message 3"
    assert history.total_tokens == 6
