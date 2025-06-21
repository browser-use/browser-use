from typing import List, Optional, Tuple

from google.genai.types import Content, Part

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	SystemMessage,
	UserMessage,
)


class GoogleMessageSerializer:
	"""Serializer for converting messages to Google Gemini format."""

	@staticmethod
	def serialize_messages(messages: List[BaseMessage]) -> Tuple[List[Content], Optional[str]]:
		"""
		Convert a list of BaseMessages to Google format, extracting system message.

		Google handles system instructions separately from the conversation, so we need to:
		1. Extract any system messages and return them separately as a string
		2. Convert the remaining messages to Content objects

		Args:
		    messages: List of messages to convert

		Returns:
		    A tuple of (formatted_messages, system_message) where:
		    - formatted_messages: List of Content objects for the conversation
		    - system_message: System instruction string or None
		"""
		formatted_messages: List[Content] = []
		system_message: Optional[str] = None

		for message in messages:
			role = message.role if hasattr(message, 'role') else None

			# Handle system/developer messages
			if isinstance(message, SystemMessage) or role in ['system', 'developer']:
				# Extract system message content as string
				if isinstance(message.content, str):
					system_message = message.content
				elif message.content is not None:
					# Handle Iterable of content parts
					parts = []
					for part in message.content:
						if part['type'] == 'text':
							parts.append(part['text'])
					system_message = '\n'.join(parts)
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
			message_parts: List[Part] = []

			# Extract content and create parts
			if isinstance(message.content, str):
				# Regular text content
				message_parts = [Part.from_text(text=message.content)]
			elif message.content is not None:
				# Handle Iterable of content parts
				text_parts = []
				for part in message.content:
					if part['type'] == 'text':
						text_parts.append(part['text'])
					elif part['type'] == 'refusal':
						text_parts.append(f'[Refusal] {part["refusal"]}')
					elif part['type'] == 'image_url':
						# For images, we'll include a placeholder text
						# In a full implementation, you'd handle images properly
						text_parts.append(f'[Image: {part["image_url"]["url"]}]')

				# Combine all text parts into a single Part
				if text_parts:
					combined_text = '\n'.join(text_parts)
					message_parts = [Part.from_text(text=combined_text)]

			# Create the Content object
			if message_parts:
				final_message = Content(role=role, parts=message_parts)
				formatted_messages.append(final_message)

		return formatted_messages, system_message
