from openai.types.chat import ChatCompletionMessageParam

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer


class N1nMessageSerializer:
	"""
	Serializer for converting between custom message types and n1n.ai message formats.

	n1n.ai uses the OpenAI-compatible API, so we can reuse the OpenAI serializer.
	"""

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[ChatCompletionMessageParam]:
		"""
		Serialize a list of browser_use messages to n1n.ai-compatible messages.

		Args:
		    messages: List of browser_use messages

		Returns:
		    List of n1n.ai-compatible messages (identical to OpenAI format)
		"""
		# n1n.ai uses the same message format as OpenAI
		return OpenAIMessageSerializer.serialize_messages(messages)
