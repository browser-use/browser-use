from openai.types.chat import ChatCompletionMessageParam

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer


class AstraflowMessageSerializer:
	"""
	Serializer for converting between custom message types and Astraflow message
	formats.

	Astraflow uses the OpenAI-compatible API, so we can reuse the OpenAI serializer.
	"""

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[ChatCompletionMessageParam]:
		"""
		Serialize a list of browser_use messages to Astraflow-compatible messages.

		Args:
		    messages: List of browser_use messages

		Returns:
		    List of Astraflow-compatible messages (identical to OpenAI format)
		"""
		# Astraflow uses the same message format as OpenAI
		return OpenAIMessageSerializer.serialize_messages(messages)
