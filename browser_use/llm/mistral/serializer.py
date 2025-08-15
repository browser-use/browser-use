from typing import TypeAlias, Union, overload

from mistralai.models import (
	AssistantMessage as MistralAssistantMessage,
)
from mistralai.models import (
	ImageURL,
	ImageURLChunk,
	TextChunk,
)
from mistralai.models import (
	SystemMessage as MistralSystemMessage,
)
from mistralai.models import (
	UserMessage as MistralUserMessage,
)

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	SystemMessage,
	UserMessage,
)

MistralMessage: TypeAlias = Union[
	MistralAssistantMessage,
	MistralSystemMessage,
	MistralUserMessage,
]


class MistralMessageSerializer:
	"""Serializer for converting between browser-use message types and Mistral message types."""

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[MistralMessage]:
		"""Serialize a list of messages to Mistral format."""
		return [MistralMessageSerializer.serialize(message) for message in messages]

	@overload
	@staticmethod
	def serialize(message: UserMessage) -> MistralUserMessage: ...

	@overload
	@staticmethod
	def serialize(message: SystemMessage) -> MistralSystemMessage: ...

	@overload
	@staticmethod
	def serialize(message: AssistantMessage) -> MistralAssistantMessage: ...

	@staticmethod
	def serialize(message: BaseMessage) -> MistralMessage:
		"""Serialize a single message to Mistral format."""
		if isinstance(message, UserMessage):
			return MistralMessageSerializer._serialize_user_message(message)
		elif isinstance(message, AssistantMessage):
			return MistralMessageSerializer._serialize_assistant_message(message)
		elif isinstance(message, SystemMessage):
			return MistralMessageSerializer._serialize_system_message(message)
		raise ValueError(f'Unknown message type: {type(message)}')

	@staticmethod
	def _serialize_user_message(message: UserMessage) -> MistralUserMessage:
		"""Convert UserMessage to MistralUserMessage."""
		if isinstance(message.content, list):
			content_parts = []
			for part in message.content:
				if isinstance(part, ContentPartTextParam):
					content_parts.append(MistralMessageSerializer._serialize_content_part_text(part))
				elif isinstance(part, ContentPartImageParam):
					content_parts.append(MistralMessageSerializer._serialize_content_part_image(part))
			return MistralUserMessage(content=content_parts)

		return MistralUserMessage(content=str(message.content))

	@staticmethod
	def _serialize_assistant_message(message: AssistantMessage) -> MistralAssistantMessage:
		"""Convert AssistantMessage to MistralAssistantMessage."""
		if message.content is None:
			return MistralAssistantMessage(content=None)

		if isinstance(message.content, str):
			return MistralAssistantMessage(content=message.content)

		if isinstance(message.content, list):
			content_parts = []
			for part in message.content:
				if isinstance(part, ContentPartTextParam):
					content_parts.append(MistralMessageSerializer._serialize_content_part_text(part))
			return MistralAssistantMessage(content=content_parts)

		return MistralAssistantMessage(content=str(message.content))

	@staticmethod
	def _serialize_system_message(message: SystemMessage) -> MistralSystemMessage:
		"""Convert SystemMessage to MistralSystemMessage."""
		if isinstance(message.content, str):
			return MistralSystemMessage(content=message.content)

		if isinstance(message.content, list):
			content_parts = []
			for part in message.content:
				if isinstance(part, ContentPartTextParam):
					content_parts.append(MistralMessageSerializer._serialize_content_part_text(part))
			return MistralSystemMessage(content=content_parts)

		return MistralSystemMessage(content=str(message.content))

	@staticmethod
	def _serialize_content_part_text(part: ContentPartTextParam) -> TextChunk:
		"""Convert a text content part to Mistral's TextChunk."""
		return TextChunk(text=part.text, type=part.type)

	@staticmethod
	def _serialize_content_part_image(part: ContentPartImageParam) -> ImageURLChunk:
		"""Convert an image content part to Mistral's ImageURLChunk."""
		return ImageURLChunk(image_url=ImageURL(url=part.image_url.url), type=part.type)
