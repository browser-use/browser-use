from openai.types.chat import ChatCompletionMessageParam

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer


class VolcengineMessageSerializer:
	"""
	Serializer for converting between custom message types and Volcengine Ark message formats.

	Ark exposes an OpenAI-compatible /chat/completions endpoint, so the OpenAI
	serializer applies unchanged — including `image_url` parts, which Ark accepts
	as data URLs.
	"""

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[ChatCompletionMessageParam]:
		"""
		Serialize a list of browser_use messages to Ark-compatible messages.

		Args:
		    messages: List of browser_use messages

		Returns:
		    List of Ark-compatible messages (identical to OpenAI format)
		"""
		return OpenAIMessageSerializer.serialize_messages(messages)
