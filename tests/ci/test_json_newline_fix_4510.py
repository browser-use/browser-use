"""Regression test for issue #4510: JSON string with literal newlines breaks parsing."""

import json
import pytest


def clean_input_for_json(s: str) -> str:
    """Escape literal newlines/tabs that break JSON parsing."""
    return s.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")


class TestIssue4510JsonNewlineCrash:
    """Test that multi-line JSON strings in tool input are parsed correctly."""

    def test_json_string_with_literal_newlines_in_value(self):
        """JSON value containing literal newline characters should parse correctly.

        When the LLM generates multi-line done-text, the resulting JSON string
        contains literal chr(10) newlines inside string values. json.loads()
        rejects these unless they are escaped.
        """
        # The \n here is a literal newline character (chr(10)), not \\n
        tool_input = '{"result": "summary\nwith\nnewlines"}'
        cleaned = clean_input_for_json(tool_input)
        parsed = json.loads(cleaned)
        assert parsed["result"] == "summary\nwith\nnewlines"

    def test_json_string_with_windows_crlf_in_value(self):
        """JSON value with Windows CRLF in string should parse correctly."""
        tool_input = '{"result": "line1\r\nline2"}'
        cleaned = clean_input_for_json(tool_input)
        parsed = json.loads(cleaned)
        assert parsed["result"] == "line1\r\nline2"

    def test_json_string_with_tabs_in_value(self):
        """JSON value with literal tabs in string should parse correctly."""
        tool_input = '{"result": "col1\tcol2"}'
        cleaned = clean_input_for_json(tool_input)
        parsed = json.loads(cleaned)
        assert parsed["result"] == "col1\tcol2"

    def test_normal_json_still_works(self):
        """Normal JSON without special characters should still parse correctly."""
        tool_input = '{"result": "normal text"}'
        cleaned = clean_input_for_json(tool_input)
        parsed = json.loads(cleaned)
        assert parsed["result"] == "normal text"

    def test_properly_escaped_json_still_works(self):
        """JSON with properly escaped \\n (backslash-n) still parses correctly."""
        # This is what correctly-formed JSON looks like in Python string form
        tool_input = '{"result": "line1\\nline2"}'  # \\n is backslash + n
        cleaned = clean_input_for_json(tool_input)
        # Our clean shouldn't affect this since there are no literal newlines
        parsed = json.loads(cleaned)
        assert parsed["result"] == "line1\nline2"

    def test_ai_done_summary_multiline(self):
        """Simulate AI returning a done summary with markdown table (literal newlines)."""
        tool_input = '{"result": "## Summary\n| Col1 | Col2 |\n|------|------|\n| val | data |"}'
        cleaned = clean_input_for_json(tool_input)
        parsed = json.loads(cleaned)
        assert "## Summary" in parsed["result"]
        assert "| Col1 |" in parsed["result"]
