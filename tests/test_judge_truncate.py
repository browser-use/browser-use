"""Tests for browser_use.agent.judge._truncate_text."""

import pytest

from browser_use.agent.judge import _truncate_text


class TestTruncateText:
    """Tests for the _truncate_text helper."""

    def test_short_text_returned_unchanged(self):
        assert _truncate_text("short", 100) == "short"

    def test_empty_text(self):
        assert _truncate_text("", 10) == ""

    def test_exact_length(self):
        text = "x" * 50
        assert _truncate_text(text, 50) == text

    def test_normal_truncation_length(self):
        """Truncated output must be exactly max_length chars."""
        text = "A" * 100
        result = _truncate_text(text, 50)
        assert len(result) == 50

    def test_normal_truncation_has_marker(self):
        text = "A" * 100
        result = _truncate_text(text, 50)
        assert result.endswith("...[text truncated]...")

    def test_from_beginning_length(self):
        """Truncated output from beginning must be exactly max_length chars."""
        text = "A" * 100
        result = _truncate_text(text, 50, from_beginning=True)
        assert len(result) == 50

    def test_from_beginning_has_marker(self):
        text = "A" * 100
        result = _truncate_text(text, 50, from_beginning=True)
        assert result.startswith("...[text truncated]")

    def test_small_max_length_no_crash(self):
        """max_length smaller than marker must not corrupt output."""
        text = "A" * 100
        result = _truncate_text(text, 10)
        assert len(result) == 10

    def test_small_max_length_from_beginning_no_crash(self):
        text = "A" * 100
        result = _truncate_text(text, 10, from_beginning=True)
        assert len(result) == 10

    def test_max_length_zero(self):
        text = "A" * 100
        assert _truncate_text(text, 0) == ""

    def test_max_length_one(self):
        text = "A" * 100
        assert len(_truncate_text(text, 1)) == 1

    def test_preserves_end_content_from_beginning(self):
        """from_beginning should keep the end of the text."""
        text = "HEAD" + "x" * 40 + "TAIL"
        result = _truncate_text(text, 30, from_beginning=True)
        assert result.endswith("TAIL")

    def test_preserves_start_content_normal(self):
        """Normal truncation should keep the start of the text."""
        text = "HEAD" + "x" * 40 + "TAIL"
        result = _truncate_text(text, 30)
        assert result.startswith("HEAD")
