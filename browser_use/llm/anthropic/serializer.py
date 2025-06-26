import json
from typing import overload

from anthropic.types import (
	Base64ImageSourceParam,
	CacheControlEphemeralParam,
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

NonSystemMessage = UserMessage | AssistantMessage


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
			# Default to png if not recognized
			media_type = 'image/png'

		return media_type, data  # type: ignore

	@staticmethod
	def _serialize_cache_control(use_cache: bool) -> CacheControlEphemeralParam | None:
		"""Serialize cache control."""
		if use_cache:
			return CacheControlEphemeralParam(type='ephemeral')
		return None

	@staticmethod
	def _serialize_content_part_text(part: ContentPartTextParam, use_cache: bool) -> TextBlockParam:
		"""Convert a text content part to Anthropic's TextBlockParam."""
		return TextBlockParam(
			text=part.text, type='text', cache_control=AnthropicMessageSerializer._serialize_cache_control(use_cache)
		)

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
	def _serialize_content_to_str(
		content: str | list[ContentPartTextParam], use_cache: bool = False
	) -> list[TextBlockParam] | str:
		"""Serialize content to a string."""
		cache_control = AnthropicMessageSerializer._serialize_cache_control(use_cache)

		if isinstance(content, str):
			if cache_control:
				return [TextBlockParam(text=content, type='text', cache_control=cache_control)]
			else:
				return content

		serialized_blocks: list[TextBlockParam] = []
		for part in content:
			if part.type == 'text':
				serialized_blocks.append(AnthropicMessageSerializer._serialize_content_part_text(part, use_cache))

		return serialized_blocks

	@staticmethod
	def _serialize_content(
		content: str | list[ContentPartTextParam | ContentPartImageParam],
		use_cache: bool = False,
	) -> str | list[TextBlockParam | ImageBlockParam]:
		"""Serialize content to Anthropic format."""
		if isinstance(content, str):
			if use_cache:
				return [TextBlockParam(text=content, type='text', cache_control=CacheControlEphemeralParam(type='ephemeral'))]
			else:
				return content

		serialized_blocks: list[TextBlockParam | ImageBlockParam] = []
		for part in content:
			if part.type == 'text':
				serialized_blocks.append(AnthropicMessageSerializer._serialize_content_part_text(part, use_cache))
			elif part.type == 'image_url':
				serialized_blocks.append(AnthropicMessageSerializer._serialize_content_part_image(part))

		return serialized_blocks

	@staticmethod
	def _serialize_tool_calls_to_content(tool_calls, use_cache: bool = False) -> list[ToolUseBlockParam]:
		"""Convert tool calls to Anthropic's ToolUseBlockParam format."""
		blocks: list[ToolUseBlockParam] = []
		for tool_call in tool_calls:
			# Parse the arguments JSON string to object

			try:
				input_obj = json.loads(tool_call.function.arguments)
			except json.JSONDecodeError:
				# If arguments aren't valid JSON, use as string
				input_obj = {'arguments': tool_call.function.arguments}

			blocks.append(
				ToolUseBlockParam(
					id=tool_call.id,
					input=input_obj,
					name=tool_call.function.name,
					type='tool_use',
					cache_control=AnthropicMessageSerializer._serialize_cache_control(use_cache),
				)
			)
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
			content = AnthropicMessageSerializer._serialize_content(message.content, use_cache=message.cache)
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
					blocks.append(
						TextBlockParam(
							text=message.content,
							type='text',
							cache_control=AnthropicMessageSerializer._serialize_cache_control(message.cache),
						)
					)
				else:
					# Process content parts (text and refusal)
					for part in message.content:
						if part.type == 'text':
							blocks.append(AnthropicMessageSerializer._serialize_content_part_text(part, use_cache=message.cache))
						# # Note: Anthropic doesn't have a specific refusal block type,
						# # so we convert refusals to text blocks
						# elif part.type == 'refusal':
						# 	blocks.append(TextBlockParam(text=f'[Refusal] {part.refusal}', type='text'))

			# Add tool use blocks if present
			if message.tool_calls:
				tool_blocks = AnthropicMessageSerializer._serialize_tool_calls_to_content(
					message.tool_calls, use_cache=message.cache
				)
				blocks.extend(tool_blocks)

			# If no content or tool calls, add empty text block
			# (Anthropic requires at least one content block)
			if not blocks:
				blocks.append(
					TextBlockParam(
						text='', type='text', cache_control=AnthropicMessageSerializer._serialize_cache_control(message.cache)
					)
				)

			# If caching is enabled or we have multiple blocks, return blocks as-is
			# Otherwise, simplify single text blocks to plain string
			if message.cache or len(blocks) > 1:
				content = blocks
			else:
				# Only simplify when no caching and single block
				single_block = blocks[0]
				if single_block['type'] == 'text' and not single_block.get('cache_control'):
					content = single_block['text']
				else:
					content = blocks

			return MessageParam(
				role='assistant',
				content=content,
			)

		else:
			raise ValueError(f'Unknown message type: {type(message)}')

	@staticmethod
	def _clean_cache_messages(messages: list[NonSystemMessage]) -> list[NonSystemMessage]:
		"""Clean cache settings so only the last cache=True message remains cached.

		Because of how Claude caching works, only the last cache message matters.
		This method automatically removes cache=True from all messages except the last one.

		Args:
			messages: List of non-system messages to clean

		Returns:
			List of messages with cleaned cache settings
		"""
		if not messages:
			return messages

		# Create a copy to avoid modifying the original
		cleaned_messages = [msg.model_copy(deep=True) for msg in messages]

		# Find the last message with cache=True
		last_cache_index = -1
		for i in range(len(cleaned_messages) - 1, -1, -1):
			if cleaned_messages[i].cache:
				last_cache_index = i
				break

		# If we found a cached message, disable cache for all others
		if last_cache_index != -1:
			for i, msg in enumerate(cleaned_messages):
				if i != last_cache_index and msg.cache:
					# Set cache to False for all messages except the last cached one
					msg.cache = False

		return cleaned_messages

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> tuple[list[MessageParam], list[TextBlockParam] | str | None]:
		"""Serialize a list of messages, extracting any system message.

		Returns:
		    A tuple of (messages, system_message) where system_message is extracted
		    from any SystemMessage in the list.
		"""
		messages = [m.model_copy(deep=True) for m in messages]

		# Separate system messages from normal messages
		normal_messages: list[NonSystemMessage] = []
		system_message: SystemMessage | None = None

		for message in messages:
			if isinstance(message, SystemMessage):
				system_message = message
			else:
				normal_messages.append(message)

		# Clean cache messages so only the last cache=True message remains cached
		normal_messages = AnthropicMessageSerializer._clean_cache_messages(normal_messages)

		# Serialize normal messages
		serialized_messages: list[MessageParam] = []
		for message in normal_messages:
			serialized_messages.append(AnthropicMessageSerializer.serialize(message))

		# Serialize system message
		serialized_system_message: list[TextBlockParam] | str | None = None
		if system_message:
			serialized_system_message = AnthropicMessageSerializer._serialize_content_to_str(
				system_message.content, use_cache=system_message.cache
			)

		return serialized_messages, serialized_system_message
