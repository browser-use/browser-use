from openai.types.chat import ChatCompletionMessageParam

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer


class AvianMessageSerializer:
	"""
	Serializer for converting between custom message types and Avian message formats.

	Avian uses an OpenAI-compatible API, so we reuse the OpenAI serializer.
	"""

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[ChatCompletionMessageParam]:
		"""
		Serialize a list of browser_use messages to Avian-compatible messages.

		Args:
		    messages: List of browser_use messages

		Returns:
		    List of Avian-compatible messages (identical to OpenAI format)
		"""
		return OpenAIMessageSerializer.serialize_messages(messages)
