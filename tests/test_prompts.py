import pytest

from browser_use.agent.prompts import SystemPrompt
from langchain_core.messages import SystemMessage
from unittest.mock import patch

class TestSystemPrompt:
    """Tests for the SystemPrompt class."""

    def test_get_system_message_content(self):
        """
        Test that the get_system_message method returns a SystemMessage
        with the expected content structure.
        """
        # Arrange
        action_description = "Test action description"
        max_actions_per_step = 5
        system_prompt = SystemPrompt(action_description, max_actions_per_step)

        # Act
        result = system_prompt.get_system_message()

        # Assert
        assert isinstance(result, SystemMessage)
        assert "You are a precise browser automation agent" in result.content
        assert action_description in result.content
        assert f"use maximum {max_actions_per_step} actions per sequence" in result.content
        assert "RESPONSE FORMAT:" in result.content
        assert "ACTIONS:" in result.content
        assert "ELEMENT INTERACTION:" in result.content
        assert "NAVIGATION & ERROR HANDLING:" in result.content
        assert "TASK COMPLETION:" in result.content
        assert "VISUAL CONTEXT:" in result.content
        assert "Form filling:" in result.content
        assert "ACTION SEQUENCING:" in result.content