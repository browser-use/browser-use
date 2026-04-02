"""Test that LLM providers correctly handle empty choices in API responses.

This tests the fix from PR #3899 which was applied to the OpenAI provider,
extended here to Groq, DeepSeek, and Cerebras providers.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import SystemMessage, UserMessage


def _make_empty_choices_response():
    """Create a mock chat completion response with an empty choices list."""
    mock_resp = MagicMock()
    mock_resp.choices = []
    return mock_resp


@pytest.mark.asyncio
async def test_groq_empty_choices_regular():
    """Groq provider raises ModelProviderError on empty choices for regular completion."""
    from browser_use.llm.groq.chat import ChatGroq

    llm = ChatGroq(model="llama-3.3-70b-versatile", api_key="test-key")

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_make_empty_choices_response())

    with patch.object(llm, "get_client", return_value=mock_client):
        with pytest.raises(ModelProviderError, match="empty `choices`"):
            await llm.ainvoke([UserMessage(content="hello")])


@pytest.mark.asyncio
async def test_deepseek_empty_choices_regular():
    """DeepSeek provider raises ModelProviderError on empty choices for regular completion."""
    from browser_use.llm.deepseek.chat import ChatDeepSeek

    llm = ChatDeepSeek(model="deepseek-chat", api_key="test-key")

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_make_empty_choices_response())

    with patch.object(llm, "get_client", return_value=mock_client):
        with pytest.raises(ModelProviderError, match="empty `choices`"):
            await llm.ainvoke([UserMessage(content="hello")])


@pytest.mark.asyncio
async def test_cerebras_empty_choices_regular():
    """Cerebras provider raises ModelProviderError on empty choices for regular completion."""
    from browser_use.llm.cerebras.chat import ChatCerebras

    llm = ChatCerebras(model="llama-3.3-70b", api_key="test-key")

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_make_empty_choices_response())

    with patch.object(llm, "get_client", return_value=mock_client):
        with pytest.raises(ModelProviderError, match="empty `choices`"):
            await llm.ainvoke([UserMessage(content="hello")])
