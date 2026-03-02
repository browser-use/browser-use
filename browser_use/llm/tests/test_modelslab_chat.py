"""Tests for ModelsLab chat provider. All mocked — no real network calls."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.llm.modelslab.chat import ChatModelsLab, MODELSLAB_API_BASE


class TestChatModelsLab:

    def test_provider_name(self):
        model = ChatModelsLab(model='llama-3-70b-chat', api_key='test')
        assert model.provider == 'modelslab'

    def test_model_name(self):
        model = ChatModelsLab(model='mixtral-8x7b', api_key='test')
        assert model.name == 'mixtral-8x7b'

    def test_default_base_url(self):
        model = ChatModelsLab(model='llama-3-70b-chat', api_key='test')
        assert str(model.base_url) == MODELSLAB_API_BASE

    def test_get_client_returns_async_openai(self):
        from openai import AsyncOpenAI
        model = ChatModelsLab(model='llama-3-70b-chat', api_key='test-key')
        client = model.get_client()
        assert isinstance(client, AsyncOpenAI)
        assert str(client.base_url).rstrip('/') == MODELSLAB_API_BASE.rstrip('/')

    @pytest.mark.asyncio
    async def test_ainvoke_returns_string(self):
        model = ChatModelsLab(model='llama-3-70b-chat', api_key='test')

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = 'Hello from ModelsLab!'
        mock_response.usage = None

        with patch.object(model, 'get_client') as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            from browser_use.llm.messages import UserMessage
            result = await model.ainvoke(
                messages=[UserMessage(content='Hello')],
                output_format=None,
            )

        assert result.completion == 'Hello from ModelsLab!'
