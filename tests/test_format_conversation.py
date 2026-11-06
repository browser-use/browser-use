"""Tests for browser_use.agent.message_manager.utils._format_conversation."""

import asyncio
import json

import pytest

from browser_use.agent.message_manager.utils import _format_conversation


class FakeMessage:
    def __init__(self, role="user", text="hello"):
        self.role = role
        self.text = text


class FakeResponse:
    def model_dump(self, exclude_unset=False):
        return {"key": "value"}


class BadResponse:
    def model_dump(self, exclude_unset=False):
        raise RuntimeError("serialization failed")


class TestFormatConversation:
    def test_none_response(self):
        """None response should not crash with AttributeError."""
        result = asyncio.run(_format_conversation([FakeMessage()], None))
        assert "(no response)" in result

    def test_normal_response(self):
        result = asyncio.run(_format_conversation([FakeMessage()], FakeResponse()))
        assert '"key": "value"' in result

    def test_failing_response_falls_back(self):
        """Response whose model_dump raises should fall back to str()."""
        result = asyncio.run(_format_conversation([FakeMessage()], BadResponse()))
        assert "BadResponse" in result

    def test_messages_formatted(self):
        result = asyncio.run(_format_conversation([FakeMessage("user", "hi")], None))
        assert "user" in result
        assert "hi" in result

    def test_empty_messages(self):
        result = asyncio.run(_format_conversation([], None))
        assert "(no response)" in result
