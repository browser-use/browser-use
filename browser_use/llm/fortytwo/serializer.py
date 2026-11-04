from openai.types.chat import ChatCompletionMessageParam

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer


class FortytwoMessageSerializer:
	"""Preserve the existing OpenAI message representation for Fortytwo."""

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[ChatCompletionMessageParam]:
		return OpenAIMessageSerializer.serialize_messages(messages)
