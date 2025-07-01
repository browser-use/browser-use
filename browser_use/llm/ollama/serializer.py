import base64
import json
from typing import Any, overload

from ollama._types import Image, Message

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	SystemMessage,
	ToolCall,
	UserMessage,
)


class OllamaMessageSerializer:
	"""Serializer for converting between custom message types and Ollama message types."""

	@staticmethod
	def _extract_text_content(content: Any) -> str:
		"""Extract text content from message content, ignoring images."""
		if content is None:
			return ''
		if isinstance(content, str):
			return content

		text_parts: list[str] = []
		for part in content:
			if hasattr(part, 'type'):
				if part.type == 'text':
					text_parts.append(part.text)
				elif part.type == 'refusal':
					text_parts.append(f'[Refusal] {part.refusal}')
			# Skip image parts as they're handled separately

		return '\n'.join(text_parts)

	@staticmethod
	def _extract_images(content: Any) -> list[Image]:
		"""Extract images from message content."""
		if content is None or isinstance(content, str):
			return []

		images: list[Image] = []
		for part in content:
			if hasattr(part, 'type') and part.type == 'image_url':
				url = part.image_url.url
				if url.startswith('data:'):
					# Handle base64 encoded images
					# Format: data:image/png;base64,<data>
					_, data = url.split(',', 1)
					# Decode base64 to bytes
					image_bytes = base64.b64decode(data)
					images.append(Image(value=image_bytes))
				else:
					# Handle URL images (Ollama will download them)
					images.append(Image(value=url))

		return images

	@staticmethod
	def _serialize_tool_calls(tool_calls: list[ToolCall]) -> list[Message.ToolCall]:
		"""Convert browser-use ToolCalls to Ollama ToolCalls."""
		ollama_tool_calls: list[Message.ToolCall] = []

		for tool_call in tool_calls:
			# Parse arguments from JSON string to dict for Ollama
			try:
				arguments_dict = json.loads(tool_call.function.arguments)
			except json.JSONDecodeError:
				# If parsing fails, wrap in a dict
				arguments_dict = {'arguments': tool_call.function.arguments}

			ollama_tool_call = Message.ToolCall(
				function=Message.ToolCall.Function(name=tool_call.function.name, arguments=arguments_dict)
			)
			ollama_tool_calls.append(ollama_tool_call)

		return ollama_tool_calls

	# region - Serialize overloads
	@overload
	@staticmethod
	def serialize(message: UserMessage) -> Message: ...

	@overload
	@staticmethod
	def serialize(message: SystemMessage) -> Message: ...

	@overload
	@staticmethod
	def serialize(message: AssistantMessage) -> Message: ...

	@staticmethod
	def serialize(message: BaseMessage) -> Message:
		"""Serialize a custom message to an Ollama Message."""

		if isinstance(message, UserMessage):
			text_content = OllamaMessageSerializer._extract_text_content(message.content)
			images = OllamaMessageSerializer._extract_images(message.content)

			ollama_message = Message(
				role='user',
				content=text_content if text_content else None,
			)

			if images:
				ollama_message.images = images

			return ollama_message

		elif isinstance(message, SystemMessage):
			text_content = OllamaMessageSerializer._extract_text_content(message.content)

			return Message(
				role='system',
				content=text_content if text_content else None,
			)

		elif isinstance(message, AssistantMessage):
			# Handle content
			text_content = None
			if message.content is not None:
				text_content = OllamaMessageSerializer._extract_text_content(message.content)

			ollama_message = Message(
				role='assistant',
				content=text_content if text_content else None,
			)

			# Handle tool calls
			if message.tool_calls:
				ollama_message.tool_calls = OllamaMessageSerializer._serialize_tool_calls(message.tool_calls)

			return ollama_message

		else:
			raise ValueError(f'Unknown message type: {type(message)}')

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[Message]:
		"""Serialize a list of browser_use messages to Ollama Messages."""
		return [OllamaMessageSerializer.serialize(m) for m in messages]
