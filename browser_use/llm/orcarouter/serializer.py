from openai.types.chat import ChatCompletionMessageParam

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer


class OrcaRouterMessageSerializer:
	"""
	Serializer for converting between custom message types and OrcaRouter message formats.

	OrcaRouter uses the OpenAI-compatible API, so we can reuse the OpenAI serializer.
	"""

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[ChatCompletionMessageParam]:
		"""
		Serialize a list of browser_use messages to OrcaRouter-compatible messages.

		Args:
		    messages: List of browser_use messages

		Returns:
		    List of OrcaRouter-compatible messages (identical to OpenAI format)
		"""
		# OrcaRouter uses the same message format as OpenAI
		return OpenAIMessageSerializer.serialize_messages(messages)
