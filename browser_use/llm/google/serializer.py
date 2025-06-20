from typing import List, Union

from google.genai import types

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	ContentPartRefusalParam,
	ContentPartTextParam,
	SystemMessage,
	UserMessage,
)


class GoogleMessageSerializer:
	"""Serializer for converting messages to Google Gemini format."""

	@staticmethod
	def serialize(message: BaseMessage) -> types.Content:
		"""
		Convert a single BaseMessage to Google Content format.

		Args:
		    message: The message to convert

		Returns:
		    A Google Content object
		"""
		# Determine the role
		if isinstance(message, SystemMessage):
			# Google doesn't have a system role in Content, system messages are handled separately
			role = 'user'  # We'll handle system messages in serialize_messages
		elif isinstance(message, UserMessage):
			role = 'user'
		elif isinstance(message, AssistantMessage):
			role = 'model'
		else:
			# Default to user for any unknown message types
			role = 'user'

		# Extract text content
		text_content = ''
		if isinstance(message.content, str):
			text_content = message.content
		elif message.content is not None:
			# Handle Iterable of content parts
			parts = []
			for part in message.content:
				if isinstance(part, ContentPartTextParam):
					parts.append(part.text)
				elif isinstance(part, ContentPartRefusalParam):
					parts.append(f'[Refusal] {part.refusal}')
				elif isinstance(part, ContentPartImageParam):
					# For images, we'll include a placeholder text
					# Google's API handles images differently via FileData
					parts.append(f'[Image: {part.image_url.url}]')
			text_content = '\n'.join(parts)

		# Create a Part object with the text content
		part = types.Part(text=text_content)

		# Create and return the Content object
		return types.Content(role=role, parts=[part])

	@staticmethod
	def serialize_messages(messages: List[BaseMessage]) -> tuple[List[types.Content], Union[types.Content, None]]:
		"""
		Convert a list of BaseMessages to Google format, extracting system message.

		Google handles system instructions separately from the conversation, so we need to:
		1. Extract any system messages and return them separately
		2. Convert the remaining messages to Content objects

		Args:
		    messages: List of messages to convert

		Returns:
		    A tuple of (contents, system_instruction) where:
		    - contents: List of Content objects for the conversation
		    - system_instruction: Content object for system instruction or None
		"""
		contents = []
		system_instruction = None
		system_parts = []

		for message in messages:
			if isinstance(message, SystemMessage):
				# Google expects system instruction as a separate parameter
				# Extract text content
				text_content = ''
				if isinstance(message.content, str):
					text_content = message.content
				else:
					# Handle Iterable of content parts
					parts = []
					for part in message.content:
						if isinstance(part, ContentPartTextParam):
							parts.append(part.text)
					text_content = '\n'.join(parts)

				system_parts.append(types.Part(text=text_content))
			else:
				# Convert non-system messages normally
				contents.append(GoogleMessageSerializer.serialize(message))

		# Create system instruction if we have system messages
		if system_parts:
			system_instruction = types.Content(
				role='user',  # System instructions use "user" role
				parts=system_parts,
			)

		return contents, system_instruction
