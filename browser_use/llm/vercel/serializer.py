from openai.types.chat import ChatCompletionMessageParam

from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer


class VercelMessageSerializer:
	"""
	Serializer for converting between custom message types and Vercel AI Gateway message formats.

	Vercel AI Gateway uses the OpenAI-compatible API, so we can reuse the OpenAI serializer.
	"""

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[ChatCompletionMessageParam]:
		"""
		Serialize a list of browser_use messages to Vercel AI Gateway-compatible messages.

		Args:
		    messages: List of browser_use messages

		Returns:
		    List of Vercel AI Gateway-compatible messages (identical to OpenAI format)
		"""
		# Vercel AI Gateway uses the same message format as OpenAI
		return OpenAIMessageSerializer.serialize_messages(messages)
