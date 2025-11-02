import base64

from google.genai.types import Content, ContentListUnion, Part

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	SystemMessage,
	UserMessage,
)


class GoogleMessageSerializer:
	"""Serializer for converting messages to Google Gemini format."""

	@staticmethod
	def _serialize_image(part: ContentPartImageParam) -> Part:
		"""Convert a ContentPartImageParam to google format image part."""
		url = part.image_url.url
		header, data = url.split(',', 1)
		image_bytes = base64.b64decode(data)
		return Part.from_bytes(data=image_bytes, mime_type='image/jpeg')

	@staticmethod
	def serialize_messages(
		messages: list[BaseMessage], include_system_in_user: bool = False
	) -> tuple[ContentListUnion, str | None]:
		"""
		Convert a list of BaseMessages to Google format, extracting system messages.

		Google handles system instructions separately, so we need to:
		1. Extract system messages and return them separately as a string.
		2. Optionally include them in the first user message if requested.

		Args:
		    messages: List of messages to convert.
		    include_system_in_user: If True, system messages are prepended to the first user message.

		Returns:
		    A tuple of (formatted_messages, system_message) where:
		      - formatted_messages: List of Content objects for the conversation.
		      - system_message: System instruction string or None.
		"""
		messages = [m.model_copy(deep=True) for m in messages]

		formatted_messages: ContentListUnion = []
		system_message: str | None = None
		system_parts: list[str] = []

		for i, message in enumerate(messages):
			role = getattr(message, 'role', None)

			# Handle system/developer messages
			if isinstance(message, SystemMessage) or role in ['system', 'developer']:
				if isinstance(message.content, str):
					if include_system_in_user:
						system_parts.append(message.content)
					else:
						system_message = message.content
				elif message.content is not None:
					parts = []
					for part in message.content or []:
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
				role = 'user'

			message_parts: list[Part] = []

			# If this is the first user message and we have system parts, prepend them
			if include_system_in_user and system_parts and role == 'user' and not formatted_messages:
				system_text = '\n\n'.join(system_parts)

				if isinstance(message.content, str):
					# Simple string content — prepend system text
					message_parts.append(Part.from_text(text=f'{system_text}\n\n{message.content}'))

				elif message.content:
					# List of content parts
					first_insert_done = False
					for part in message.content:
						# Insert system text before the first part, even if it's an image
						if not first_insert_done:
							message_parts.append(Part.from_text(text=system_text))
							first_insert_done = True

						if part.type == "text":
							message_parts.append(Part.from_text(text=part.text))
						elif part.type == "refusal":
							message_parts.append(Part.from_text(text=f'[Refusal] {part.refusal}'))
						elif part.type == "image_url":
							image_part = GoogleMessageSerializer._serialize_image(part)
							message_parts.append(image_part)

				else:
					# Message has no content at all → still include system text
					message_parts.append(Part.from_text(text=system_text))

				system_parts = []
			else:
				# Extract content and create parts normally
				if isinstance(message.content, str):
					message_parts = [Part.from_text(text=message.content)]
				elif message.content is not None:
					for part in message.content or []:
						if part.type == 'text':
							message_parts.append(Part.from_text(text=part.text))
						elif part.type == 'refusal':
							message_parts.append(Part.from_text(text=f'[Refusal] {part.refusal}'))
						elif part.type == 'image_url':
							image_part = GoogleMessageSerializer._serialize_image(part)
							message_parts.append(image_part)

			# Create the Content object
			if message_parts:
				final_message = Content(role=role, parts=message_parts)
				formatted_messages.append(final_message)  # type: ignore

		return formatted_messages, system_message
