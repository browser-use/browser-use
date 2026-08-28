"""
A3M Router message serializer.

Converts browser-use BaseMessage objects to A3M Router format.
A3M uses OpenAI-compatible API, so we delegate to the existing OpenAI serializer.
"""

from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer


class A3MMessageSerializer:
    """Serializer for converting browser-use messages to A3M Router format.

    A3M Router uses the OpenAI-compatible API, so we reuse the OpenAI serializer.
    """

    @staticmethod
    def serialize(messages: list[BaseMessage]) -> list[ChatCompletionMessageParam]:
        """Convert a list of browser-use BaseMessage objects to A3M Router format.

        Args:
            messages: List of BaseMessage objects from browser-use

        Returns:
            List of message dicts in A3M Router format (OpenAI-compatible)
        """
        # A3M uses OpenAI-compatible format, delegate to existing serializer
        return OpenAIMessageSerializer.serialize_messages(messages)
