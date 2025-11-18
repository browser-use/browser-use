import base64

from google.genai.types import Content, ContentListUnion, Part

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	SystemMessage,
	UserMessage,
)


class GoogleMessageSerializer:
	"""Serializer for converting messages to Google Gemini format."""

	@staticmethod
	def serialize_messages(
		messages: list[BaseMessage], include_system_in_user: bool = False
	) -> tuple[ContentListUnion, str | None]:
		"""
		Convert a list of BaseMessages to Google format, extracting system message.

		Google handles system instructions separately from the conversation, so we need to:
		1. Extract any system messages and return them separately as a string (or include in first user message if flag is set)
		2. Convert the remaining messages to Content objects

		Args:
		    messages: List of messages to convert
		    include_system_in_user: If True, system/developer messages are prepended to the first user message

		Returns:
		    A tuple of (formatted_messages, system_message) where:
		    - formatted_messages: List of Content objects for the conversation
		    - system_message: System instruction string or None
		"""

		messages = [m.model_copy(deep=True) for m in messages]

		formatted_messages: ContentListUnion = []
		system_message: str | None = None
		system_parts: list[str] = []

		for i, message in enumerate(messages):
			role = message.role if hasattr(message, 'role') else None

			# Handle system/developer messages
			if isinstance(message, SystemMessage) or role in ['system', 'developer']:
				# Extract system message content as string
				if isinstance(message.content, str):
					if include_system_in_user:
						system_parts.append(message.content)
					else:
						system_message = message.content
				elif message.content is not None:
					# Handle Iterable of content parts
					parts = []
					for part in message.content:
						if part.type == 'text':
							parts.append(part.text)
					combined_text = '\n'.join(parts)
					if include_system_in_user:
						system_parts.append(combined_text)
					else:
						system_message = combined_text
				continue

			# Determine the role for non-system messages
			if isinstance(message, UserMessage):
				role = 'user'
			elif isinstance(message, AssistantMessage):
				role = 'model'
			else:
				# Default to user for any unknown message types
				role = 'user'

			# Initialize message parts
			message_parts: list[Part] = []

			# If this is the first user message and we have system parts, prepend them
			if include_system_in_user and system_parts and role == 'user' and not formatted_messages:
				system_text = '\n\n'.join(system_parts)
				if isinstance(message.content, str):
					message_parts.append(Part.from_text(text=f'{system_text}\n\n{message.content}'))
				else:
					# Add system text as the first part
					message_parts.append(Part.from_text(text=system_text))
				system_parts = []  # Clear after using
			else:
				# Extract content and create parts normally
				if isinstance(message.content, str):
					# Regular text content
					message_parts = [Part.from_text(text=message.content)]
				elif message.content is not None:
					# Handle Iterable of content parts
					for part in message.content:
						if part.type == 'text':
							message_parts.append(Part.from_text(text=part.text))
						elif part.type == 'refusal':
							message_parts.append(Part.from_text(text=f'[Refusal] {part.refusal}'))
						elif part.type == 'image_url':
							# Handle images
							url = part.image_url.url

							# Format: data:image/jpeg;base64,<data>
							header, data = url.split(',', 1)
							# Decode base64 to bytes
							image_bytes = base64.b64decode(data)

							# Add image part
							image_part = Part.from_bytes(data=image_bytes, mime_type='image/jpeg')

							message_parts.append(image_part)

			# Create the Content object
			if message_parts:
				final_message = Content(role=role, parts=message_parts)
				# for some reason, the type checker is not able to infer the type of formatted_messages
				formatted_messages.append(final_message)  # type: ignore

		return formatted_messages, system_message
