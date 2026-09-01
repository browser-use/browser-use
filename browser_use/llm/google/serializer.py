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
		system_parts: list[str] = []
		first_user_message_serialized = False

		for i, message in enumerate(messages):
			role = message.role if hasattr(message, 'role') else None

			# Handle system/developer messages
			if isinstance(message, SystemMessage) or role in ['system', 'developer']:
				# Collect the text of every system message; the last one must not overwrite the earlier ones
				if isinstance(message.content, str):
					system_parts.append(message.content)
				elif message.content is not None:
					# Handle Iterable of content parts
					parts = []
					for part in message.content:
						if part.type == 'text':
							parts.append(part.text)
					system_parts.append('\n'.join(parts))
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

			# Prepend pending system parts to the first user message, even if a
			# model turn was already serialized. Clearing system_parts prevents
			# later user messages from receiving the same prefix.
			system_text = None
			# Merge into the *first* user message. An earlier assistant turn must not disqualify it,
			# but a user message that has already been serialized must: the merge target is gone, so
			# the text falls through to the separate system instruction instead.
			if include_system_in_user and system_parts and role == 'user' and not first_user_message_serialized:
				system_text = '\n\n'.join(system_parts)
				system_parts = []  # Clear after using

			# Extract content and create parts
			if isinstance(message.content, str):
				# Regular text content
				text = f'{system_text}\n\n{message.content}' if system_text is not None else message.content
				message_parts.append(Part.from_text(text=text))
			else:
				if system_text is not None:
					# Add system text as the first part, the message's own parts still follow
					message_parts.append(Part.from_text(text=system_text))
				if message.content is not None:
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

							# Use the media_type from ImageURL, which correctly identifies the image format
							mime_type = part.image_url.media_type

							# Add image part
							image_part = Part.from_bytes(data=image_bytes, mime_type=mime_type)

							message_parts.append(image_part)

			# Create the Content object
			if message_parts:
				final_message = Content(role=role, parts=message_parts)
				# for some reason, the type checker is not able to infer the type of formatted_messages
				formatted_messages.append(final_message)  # type: ignore
				if role == 'user':
					first_user_message_serialized = True

		# Whatever is left was never merged into a user message, so it becomes the separate system
		# instruction. With include_system_in_user=False that is every system message. With it set,
		# it is the messages that had no first user message to merge into, either because the
		# conversation contains none or because one was already serialized before they arrived.
		system_message = '\n\n'.join(system_parts) if system_parts else None

		return formatted_messages, system_message
