from typing import overload

from anthropic.types import (
	Base64ImageSourceParam,
	ImageBlockParam,
	MessageParam,
	TextBlockParam,
	ToolUseBlockParam,
	URLImageSourceParam,
)

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	SupportedImageMediaType,
	SystemMessage,
	UserMessage,
)


class AnthropicMessageSerializer:
	"""Serializer for converting between custom message types and Anthropic message param types."""

	@staticmethod
	def _is_base64_image(url: str) -> bool:
		"""Check if the URL is a base64 encoded image."""
		return url.startswith('data:image/')

	@staticmethod
	def _parse_base64_url(url: str) -> tuple[SupportedImageMediaType, str]:
		"""Parse a base64 data URL to extract media type and data."""
		# Format: data:image/jpeg;base64,<data>
		if not url.startswith('data:'):
			raise ValueError(f'Invalid base64 URL: {url}')

		header, data = url.split(',', 1)
		media_type = header.split(';')[0].replace('data:', '')

		# Ensure it's a supported media type
		supported_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
		if media_type not in supported_types:
			# Default to jpeg if not recognized
			media_type = 'image/png'

		return media_type, data  # type: ignore

	@staticmethod
	def _serialize_content_part_text(part: ContentPartTextParam) -> TextBlockParam:
		"""Convert a text content part to Anthropic's TextBlockParam."""
		return TextBlockParam(text=part.text, type='text')

	@staticmethod
	def _serialize_content_part_image(part: ContentPartImageParam) -> ImageBlockParam:
		"""Convert an image content part to Anthropic's ImageBlockParam."""
		url = part.image_url.url

		if AnthropicMessageSerializer._is_base64_image(url):
			# Handle base64 encoded images
			media_type, data = AnthropicMessageSerializer._parse_base64_url(url)
			return ImageBlockParam(
				source=Base64ImageSourceParam(
					data=data,
					media_type=media_type,
					type='base64',
				),
				type='image',
			)
		else:
			# Handle URL images
			return ImageBlockParam(source=URLImageSourceParam(url=url, type='url'), type='image')

	@staticmethod
	def _serialize_content_to_str(content: str | list[ContentPartTextParam]) -> str | list[TextBlockParam]:
		"""Serialize content to a string."""
		if isinstance(content, str):
			return content

		serialized_blocks: list[TextBlockParam] = []
		for part in content:
			if part.type == 'text':
				serialized_blocks.append(AnthropicMessageSerializer._serialize_content_part_text(part))

		return serialized_blocks

	@staticmethod
	def _serialize_content(
		content: str | list[ContentPartTextParam | ContentPartImageParam],
	) -> str | list[TextBlockParam | ImageBlockParam]:
		"""Serialize content to Anthropic format."""
		if isinstance(content, str):
			return content

		serialized_blocks: list[TextBlockParam | ImageBlockParam] = []
		for part in content:
			if part.type == 'text':
				serialized_blocks.append(AnthropicMessageSerializer._serialize_content_part_text(part))
			elif part.type == 'image_url':
				serialized_blocks.append(AnthropicMessageSerializer._serialize_content_part_image(part))

		return serialized_blocks

	@staticmethod
	def _serialize_tool_calls_to_content(tool_calls) -> list[ToolUseBlockParam]:
		"""Convert tool calls to Anthropic's ToolUseBlockParam format."""
		blocks: list[ToolUseBlockParam] = []
		for tool_call in tool_calls:
			# Parse the arguments JSON string to object
			import json

			try:
				input_obj = json.loads(tool_call.function.arguments)
			except json.JSONDecodeError:
				# If arguments aren't valid JSON, use as string
				input_obj = {'arguments': tool_call.function.arguments}

			blocks.append(ToolUseBlockParam(id=tool_call.id, input=input_obj, name=tool_call.function.name, type='tool_use'))
		return blocks

	# region - Serialize overloads
	@overload
	@staticmethod
	def serialize(message: UserMessage) -> MessageParam: ...

	@overload
	@staticmethod
	def serialize(message: SystemMessage) -> SystemMessage: ...

	@overload
	@staticmethod
	def serialize(message: AssistantMessage) -> MessageParam: ...

	@staticmethod
	def serialize(message: BaseMessage) -> MessageParam | SystemMessage:
		"""Serialize a custom message to an Anthropic MessageParam.

		Note: Anthropic doesn't have a 'system' role. System messages should be
		handled separately as the system parameter in the API call, not as a message.
		If a SystemMessage is passed here, it will be converted to a user message.
		"""
		if isinstance(message, UserMessage):
			content = AnthropicMessageSerializer._serialize_content(message.content)
			return MessageParam(role='user', content=content)

		elif isinstance(message, SystemMessage):
			# Anthropic doesn't have system messages in the messages array
			# System prompts are passed separately. Convert to user message.
			return message

		elif isinstance(message, AssistantMessage):
			# Handle content and tool calls
			blocks: list[TextBlockParam | ToolUseBlockParam] = []

			# Add content blocks if present
			if message.content is not None:
				if isinstance(message.content, str):
					blocks.append(TextBlockParam(text=message.content, type='text'))
				else:
					# Process content parts (text and refusal)
					for part in message.content:
						if part.type == 'text':
							blocks.append(AnthropicMessageSerializer._serialize_content_part_text(part))
						# # Note: Anthropic doesn't have a specific refusal block type,
						# # so we convert refusals to text blocks
						# elif part.type == 'refusal':
						# 	blocks.append(TextBlockParam(text=f'[Refusal] {part.refusal}', type='text'))

			# Add tool use blocks if present
			if message.tool_calls:
				tool_blocks = AnthropicMessageSerializer._serialize_tool_calls_to_content(message.tool_calls)
				blocks.extend(tool_blocks)

			# If no content or tool calls, add empty text block
			# (Anthropic requires at least one content block)
			if not blocks:
				blocks.append(TextBlockParam(text='', type='text'))

			return MessageParam(
				role='assistant',
				content=blocks if len(blocks) > 1 else blocks[0].get('text', ''),  # type: ignore
			)

		else:
			raise ValueError(f'Unknown message type: {type(message)}')

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> tuple[list[MessageParam], str | list[TextBlockParam] | None]:
		"""Serialize a list of messages, extracting any system message.

		Returns:
		    A tuple of (messages, system_message) where system_message is extracted
		    from any SystemMessage in the list.
		"""
		messages = [m.model_copy(deep=True) for m in messages]

		serialized_messages: list[MessageParam] = []
		system_message: str | list[TextBlockParam] | None = None

		for message in messages:
			result = AnthropicMessageSerializer.serialize(message)
			if isinstance(result, SystemMessage):
				# Keep the SystemMessage as-is
				system_message = AnthropicMessageSerializer._serialize_content_to_str(result.content)
			else:
				serialized_messages.append(result)

		return serialized_messages, system_message
