"""Tests for judge respecting use_vision setting."""

import tempfile
from pathlib import Path

import pytest

from browser_use.agent.judge import construct_judge_messages
from browser_use.llm.messages import ContentPartImageParam


class TestJudgeUseVision:
    """Test that construct_judge_messages respects use_vision parameter."""

    @pytest.fixture
    def sample_screenshot_paths(self):
        """Create temporary screenshot files for testing."""
        temp_files = []
        for i in range(3):
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                # Write a minimal valid PNG header
                f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')
                f.write(b'\x00' * 20)  # Minimal image data
                temp_files.append(f.name)
        yield temp_files
        # Cleanup
        for f in temp_files:
            Path(f).unlink(missing_ok=True)

    def test_use_vision_true_includes_screenshots(self, sample_screenshot_paths):
        """When use_vision=True, screenshots should be included."""
        messages = construct_judge_messages(
            task="Test task",
            final_result="Test result",
            agent_steps=["Step 1", "Step 2"],
            screenshot_paths=sample_screenshot_paths,
            use_vision=True,
        )
        
        # Check that the user message contains image parts
        user_message = messages[1]
        image_parts = [
            part for part in user_message.content 
            if isinstance(part, ContentPartImageParam)
        ]
        assert len(image_parts) > 0, "Screenshots should be included when use_vision=True"

    def test_use_vision_false_excludes_screenshots(self, sample_screenshot_paths):
        """When use_vision=False, screenshots should NOT be included."""
        messages = construct_judge_messages(
            task="Test task",
            final_result="Test result",
            agent_steps=["Step 1", "Step 2"],
            screenshot_paths=sample_screenshot_paths,
            use_vision=False,
        )
        
        # Check that the user message contains NO image parts
        user_message = messages[1]
        image_parts = [
            part for part in user_message.content 
            if isinstance(part, ContentPartImageParam)
        ]
        assert len(image_parts) == 0, "Screenshots should NOT be included when use_vision=False"

    def test_use_vision_auto_includes_screenshots(self, sample_screenshot_paths):
        """When use_vision='auto', screenshots should be included (same as True for judge)."""
        messages = construct_judge_messages(
            task="Test task",
            final_result="Test result",
            agent_steps=["Step 1", "Step 2"],
            screenshot_paths=sample_screenshot_paths,
            use_vision='auto',
        )
        
        # Check that the user message contains image parts
        user_message = messages[1]
        image_parts = [
            part for part in user_message.content 
            if isinstance(part, ContentPartImageParam)
        ]
        assert len(image_parts) > 0, "Screenshots should be included when use_vision='auto'"

    def test_use_vision_default_includes_screenshots(self, sample_screenshot_paths):
        """Default behavior (use_vision not specified) should include screenshots."""
        messages = construct_judge_messages(
            task="Test task",
            final_result="Test result",
            agent_steps=["Step 1", "Step 2"],
            screenshot_paths=sample_screenshot_paths,
            # use_vision not specified, defaults to True
        )
        
        # Check that the user message contains image parts
        user_message = messages[1]
        image_parts = [
            part for part in user_message.content 
            if isinstance(part, ContentPartImageParam)
        ]
        assert len(image_parts) > 0, "Screenshots should be included by default"

    def test_use_vision_false_message_shows_zero_screenshots(self, sample_screenshot_paths):
        """When use_vision=False, message should indicate 0 screenshots attached."""
        messages = construct_judge_messages(
            task="Test task",
            final_result="Test result",
            agent_steps=["Step 1", "Step 2"],
            screenshot_paths=sample_screenshot_paths,
            use_vision=False,
        )
        
        # Check that the user message text indicates 0 screenshots
        user_message = messages[1]
        text_parts = [
            part for part in user_message.content 
            if hasattr(part, 'text')
        ]
        assert len(text_parts) > 0
        text_content = text_parts[0].text
        assert "0 screenshots from execution are attached" in text_content

    def test_empty_screenshot_paths_no_error(self):
        """Empty screenshot_paths should not cause errors regardless of use_vision."""
        # Should not raise any errors
        messages_true = construct_judge_messages(
            task="Test task",
            final_result="Test result",
            agent_steps=["Step 1"],
            screenshot_paths=[],
            use_vision=True,
        )
        messages_false = construct_judge_messages(
            task="Test task",
            final_result="Test result",
            agent_steps=["Step 1"],
            screenshot_paths=[],
            use_vision=False,
        )
        
        assert len(messages_true) == 2
        assert len(messages_false) == 2

